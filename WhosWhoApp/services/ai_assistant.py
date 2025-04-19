import os
import asyncio
import concurrent.futures
from huggingface_hub import InferenceClient
from datetime import datetime

from django.conf import settings
from ..models import StaffProfile
from tenacity import retry, stop_after_attempt, wait_exponential
import re
import logging

logging.basicConfig(level=logging.DEBUG)

class AIAssistant:
    # Status constants
    STATUS_AVAILABLE = 'available'
    STATUS_UNAVAILABLE = 'unavailable'

    def __init__(self):
        self.api_token = settings.HUGGINGFACE_API_TOKEN
        self.model_name = os.environ.get('HUGGINGFACE_MODEL_NAME', 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B')
        self.conversation_history = []
        if self.api_token:
            self.client = InferenceClient(api_key=self.api_token)
        else:
            self.client = None

    def add_to_history(self, message, is_user=True):
        self.conversation_history.append({
            'role': 'user' if is_user else 'assistant',
            'content': message
        })

    def get_availability_status(self, staff):
        if staff.status == self.STATUS_AVAILABLE:
            return "Available"
        elif staff.custom_status:
            return f"Unavailable - {staff.custom_status}"
        return "Unavailable"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=4, max=20))
    def _make_api_request(self, prompt):
        # Force database to refresh staff data
        StaffProfile.objects.all().select_for_update(skip_locked=True)
        
        base_params = {
            "prompt": prompt,
            "stream": False,
            "do_sample": True,
            "top_p": 0.9,
        }
        
        # Model-specific configurations because theres diffrance in capability. DS is more powerful than Mistral
        model_configs = {
            "deepseek": {
                "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
                "temperature": 0.6,
                "max_new_tokens": 250,
                "repetition_penalty": 1.1,
                "timeout": 30
            },
            "mistral": {
                "model": "mistralai/Mistral-Nemo-Instruct-2407",
                "temperature": 0.55,
                "max_new_tokens": 200,
                "repetition_penalty": 1.05,
                "timeout": 10
            }
        }

        def try_model(model_type):
            config = model_configs[model_type]
            params = {**base_params, **config}
            self.model_name = params["model"]
            timeout = params.pop("timeout")
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self.client.text_generation, **params)
                try:
                    return future.result(timeout=timeout)
                except Exception as e:
                    logging.error(f"Error with {model_type} model: {str(e)}")
                    raise e

        try:
            logging.info("Attempting DeepSeek model")
            return try_model("deepseek")
        except Exception:
            logging.info("Switching to Mistral model")
            return try_model("mistral")

    def clean_response(self, text):
        """Thoroughly clean AI responses to remove all reasoning and thinking text"""
        
        # First, aggressively remove all think tags and their content
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        
        # Extract content after FINAL_ANSWER: if present
        final_answer_match = re.search(r'FINAL_ANSWER:(.*?)(?=$)', text, re.DOTALL)
        if final_answer_match:
            text = final_answer_match.group(1).strip()
        
        # If the response doesn't start with our expected format, extract the relevant parts
        expected_starts = ["The best matched staff member", "Sorry, from my observation"]
        if not any(text.strip().startswith(start) for start in expected_starts):
            # Look for the standard responses anywhere in the text
            for pattern in expected_starts:
                if pattern in text:
                    # Extract everything from this pattern to the end and use that
                    text = pattern + text.split(pattern, 1)[1]
                    break
        
        # Handle cases where no expected pattern is found but there are staff links
        if not any(pattern in text for pattern in expected_starts):
            staff_link_match = re.search(r'<a href="/staff/\d+" class="staff-link">[^<]+</a>', text)
            if staff_link_match:
                # Extract the staff information and rebuild in standard format
                staff_link = staff_link_match.group(0)
                availability_match = re.search(r'(?:Available|Unavailable[^\.]*)', text)
                availability = f". Status: {availability_match.group(0)}" if availability_match else ""
                text = f"The best matched staff member is {staff_link}{availability}."
        
        # Comprehensive list of reasoning starter phrases to remove along with their content
        reasoning_patterns = [
            # General analysis indicators
            r'(?i)(?:okay|alright|let me|i will|looking at|analyzing|based on|considering|first|initially).*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)(?:i see that|i notice that|i understand that|i can help|i checked|after reviewing).*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)here\'s (?:what|why|how).*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)(?:step|steps).*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)to answer this.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)from my analysis.*?(?=The best matched staff member|Sorry, from my observation|$)',
            
            # Question parsing indicators
            r'(?i)the user is (?:asking|looking for|trying to find|wants to know).*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)this query is about.*?(?=The best matched staff member|Sorry, from my observation|$)',
            
            # Staff comparison indicators
            r'(?i)comparing the staff.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)looking at the profiles.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'(?i)among the available staff.*?(?=The best matched staff member|Sorry, from my observation|$)',
            
            # More direct thinking/reasoning extraction patterns
            r'Thinking:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Let me analyze.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'First, I need to.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'I will check.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Let\'s see.*?(?=The best matched staff member|Sorry, from my observation|$)',
            
            # Remove greetings
            r'Hello! I\'m the Who\'s Who AI Staff Finder\. How can I help you today\?',
        ]
        
        # Apply all reasoning patterns
        for pattern in reasoning_patterns:
            text = re.sub(pattern, '', text, flags=re.DOTALL)
        
        # Remove any numbered or bullet-pointed reasoning
        text = re.sub(r'\d+\.\s+.*?(?=The best matched staff member|Sorry, from my observation|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'\*\s+.*?(?=The best matched staff member|Sorry, from my observation|$)', '', text, flags=re.DOTALL)
        
        # Preserve staff links
        staff_links = []
        seen_staff_ids = set()
        staff_link_pattern = r'<a href="/staff/(\d+)" class="staff-link">([^<]+)</a>'
        
        # Process staff links
        for match in re.finditer(staff_link_pattern, text):
            staff_id = match.group(1)
            if staff_id not in seen_staff_ids:
                seen_staff_ids.add(staff_id)
                staff_links.append(match.group(0))
                text = text.replace(match.group(0), f'STAFFLINK_{len(staff_links)-1}_PLACEHOLDER')
        
        # Final cleanup of formatting
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        # Restore staff links
        for i, link in enumerate(staff_links):
            text = text.replace(f'STAFFLINK_{i}_PLACEHOLDER', link)
        
        # Remove duplicate sentences
        sentences = text.split('.')
        unique_sentences = []
        seen_sentences = set()
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence.lower() not in seen_sentences:
                unique_sentences.append(sentence)
                seen_sentences.add(sentence.lower())
        
        text = '. '.join(unique_sentences)
        if text and not text.endswith('.'):
            text += '.'
            
        # Final safety check: If we've mangled the response too much, return a simple fallback
        if len(text.strip()) < 10 and staff_links:
            text = f"The best matched staff member is {staff_links[0]}."
        
        return text.strip()

    def format_conversation_history(self):
        """Format the conversation history for inclusion in prompts"""
        if not self.conversation_history:
            return ""
            
        formatted_history = "Recent conversation history:\n"
        for message in self.conversation_history[-5:]:  # Limit to last 5 messages to avoid context overflow
            role = "User" if message["role"] == "user" else "Assistant"
            formatted_history += f"{role}: {message['content']}\n\n"
        
        return formatted_history

    def generate_prompt(self, user_query, staff_info, context_text=None, is_email_request=False):
        # Get formatted conversation history
        conversation_context = self.format_conversation_history()

        if is_email_request:
            return f"""<s>[INST] Recent conversation context:
{conversation_context}
{context_text or ""}

Write a professional email:
- Concise and friendly.
- Avoid mentioning IDs or technical details.
- Use the recipient's name in the greeting.

Format as:
Subject: [Brief subject]

Dear [Staff Member],

[Email content]

Best regards,
[Sender]

[/INST]"""
        else:
            return f"""<s>[INST] {conversation_context}
IMPORTANT: You MUST wrap ALL your analysis, greetings, and thinking process in "<think>" tags before providing your final answer.
YOU MUST FOLLOW THIS EXACT FORMAT:
<think>
[PUT ALL YOUR THINKING HERE, INCLUDING:]
- Initial greeting
- Analysis of the query
- Review of staff profiles
- Reasoning about matches
- ANY other thoughts or analysis
</think>

FINAL_ANSWER:
[SINGLE CLEAN RESPONSE WITH NO ANALYSIS OR GREETING]

Here is our staff directory:

{staff_info}


RESPONSE GUIDELINES:

- ALWAYS MENTION THE BEST MATCHED STAFF REGARDLESS OF THEIR AVAILABILITY STATUS
- ONLY MENTION AN ALTERNATIVE IF THEY ARE AVAILABLE, AND THEIR ROLES OR SKILLS ARE RELATED TO THE USERS QUERY
- IF BEST MATCHED STAFF MEMBER IS AVAILABLE, DO NOT MENTION ANY ALTERNATIVE STAFF MEMBERS ALONG WITH THEM
- MUST NOT MENTION ANY MATCHED ALTERNATIVE STAFF MEMBERS IF THEY ARE UNAVAILABLE
- THE MENTION OF BEST MATCHED STAFF IS NOT DEPENDANT ON AVAILABILITY
- USE THE EXACT HTML FORMAT PROVIDED BELOW FOR STAFF LINKS
- IN YOUR RESPONSE DO NOT INCLUDE YOUR THOUGHT PROCESS
- KEEP YOUR RESPONSE CONCISE 
- USERS MAY MAKE TYPOS SO TRY TO NORMALISE THE TEXT OF THE USER QUERY AS MUCH AS POSSIBLE
- ONLY MENTION ALTENRATIVE STAFF MEMBER IF APPROPRIATE
- ALTERNATIVE STAFF MEMBER MENTIONS (IF APPLICABLE) MUST BE LIMITED TO ONE
- EXPLICITLY INCLUDE THE CURRENT AVAILABILITY [Status] OF EACH STAFF MEMBER YOU MENTION IN YOUR RESPONSE
- IMPORTANT: For staff mentions you MUST use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a>
- IMPORTANT: ENSURE YOUT RESPONSES CORRECTLY, ACCURATELY AND DIRECTLY ANSWERS THE USER QUERY BEFORE RETURNING A RESPONSE
- IMPORTANT: FOR QUERIES RELATED TO ACADEMIC ACHIEVEMENTS, RESEARCH OR QUALIFICATIONS, YOU MUST THOROUGHLY CHECK THE STAFF MEMBERS [About] SECTION TO ENSURE ACCURACY as [About] is the field that acts as the 'about me' section for each staff members profile.
- IMPORTANT: you must NOT simply make deciscions based on the intital information you see ragarding staff members, you MUST make a thotough check of ALL the information WITHIN the staff members profiles to ensure you are making the most accurate and correct decision possible.
Important matching guidelines:
- Use your knowledge to understand relationships between similar skills and terms (e.g., "domain x" relates to "domain x" which relates to "tool x" and staff x has this tool in his skillset therefore he is a match)
- Look for both exact matches and semantically related skills in staff profiles
- Consider the broader context of roles and how they relate to the requested expertise
- ONLY mention an alternative if they are available and their skills or roles are related to the user query. when mentioning an alternative staff member, make sure to ONLY mention the skills of theirs that are MOST relevant to the user query. If their skills are not directly or strongly related to the user query, do not mention that staff member as an alternative at all.
- The best match is the staff member whose skills and roles are most relevant to the user query. If its close, choose the staff member with the most skills related to the user query OR the staff member with the most relevant roles related to the user query. Put yourself in the users shoes and think about who would be the best person to help them. roles and skills both compliment each other so consider both when making a decision. best match usually has a good combination of relevant roles and skills.
- If you mention skills as part of the reason for best match or alternative (if any), make sure to ONLY mention their skills that are MOST relevant to the user query.
- Be consistant with your matching. Different phrasing of the same query should result in the same staff member being mentioned. 
- IMPORTANT: You MUST start with "<think>" followed by your reasoning process, then "</think>" BEFORE THE TEXT "FINAL_ANSWER:", which must then be followed by your final answer with no thinking or analysis.
- IMPORTANT: For staff mentions you MUST use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a>
- IMPORTANT: include the current availability status of each staff member you mention in your response.
- IMPORTANT: you must NOT simply make deciscions based on the intital information you see ragarding staff members, you MUST make a thotough check of ALL the information WITHIN the staff members profiles to ensure you are making the most accurate and correct decision possible.
- IMPORTANT: verify your response before returning it to ensure you are not making any mistakes or errors in your response.
- THE WORDS "FINAL_ANSWER:" MUST APPEAR EXACTLY ONCE IN YOUR RESPONSE, AFTER ALL THINKING AND BEFORE THE ACTUAL ANSWER
- 'THINKING' SHOULD BE DONE IN THE BACKGROUND AND NOT INCLUDED IN THE FINAL OUTPUT
- ANALYSIS, REASONING AND STAFF COMPARISONS SHOULD BE DONE IN THE BACKGROUND AND NOT INCLUDED IN THE FINAL OUTPUT
- FINAL OUTPUT MUST BE A DIRECT AND CONCISE ANSWER TO THE USER QUERY
- IMPORTANT: AVAILABILITY STATUS UPDATES IN REAL TIME, SO MAKE SURE TO ALWAYS CHECK THE STATUS OF STAFF MEMBERS BEFORE RESPONDING
- be concise in your responses, make subsequet thurough checks of ALL details and ALL fields within ALL staff profiles before making your response to ensure accuracy and make sure you use use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> format for staff links in every response where you mention staff member/s.
- **ABSOLUTELY NO INTERNAL REASONING, GREETING, OR ANALYSIS SHOULD APPEAR IN THE FINAL OUTPUT, YOU MUST ONLY REASON IN THE BACKGROUND. ONLY THE FINAL, CONCISE ANSWER TO THE USER QUERY.**

Question: {user_query} [/INST]"""

    def get_response(self, user_query):
        if not self.client:
            return "AI assistant is currently unavailable. Please contact the administrator to set up the Hugging Face API token."

        try:
            # Force fresh query of staff data
            all_staff = StaffProfile.objects.all().select_for_update(skip_locked=True)
            staff_info = "\n".join([
                f"Staff Member: {staff.name}"
                f"\nPrimary Role: {staff.role}"
                f"\nRole Description: {staff.bio or 'Not specified'}"
                f"\nDepartment: {staff.department}"
                f"\nCore Skills: {staff.skills or 'Not specified'}"
                f"\nAbout: {staff.about_me or 'Not specified'}"
                f"\nStatus: {self.get_availability_status(staff)}"
                f"\nEmail: {staff.email}"
                f"\nLocation: {staff.location or 'Not specified'}"
                f"\nID: {staff.id}\n"
                for staff in all_staff
            ])

            email_phrases = [
                'write an email', 'compose an email', 'make email',
                'create an email', 'draft an email', 'send an email', 'write email'
            ]
            is_email_request = any(phrase in user_query.lower() for phrase in email_phrases)

            logging.debug(f"User Query: {user_query}, Detected Email Request: {is_email_request}")

            # Add timestamp to force unique prompts
            timestamp = datetime.now().isoformat()
            prompt = self.generate_prompt(f"{user_query} [Timestamp: {timestamp}]", staff_info, None, is_email_request)

            try:
                response = self._make_api_request(prompt)
                generated_text = ""
                for chunk in response:
                    if isinstance(chunk, str):
                        generated_text += chunk
                    else:
                        generated_text += chunk.get("generated_text", "")

                # First clean via the clean_response method
                cleaned_response = self.clean_response(generated_text)
                
                # Secondary safeguard: If internal reasoning is still visible
                reasoning_indicators = [
                    "let me", "i will", "looking at", "analyzing", "based on", "considering", 
                    "first", "initially", "thinking", "let's see", "i see that", "i understand",
                    "after reviewing", "here's what", "the user is asking", "okay, so the user"
                ]
                
                if any(indicator in cleaned_response.lower() for indicator in reasoning_indicators):
                    # Extract just the final answer if possible
                    for pattern in ["The best matched staff member", "Sorry, from my observation"]:
                        if pattern in cleaned_response:
                            cleaned_response = pattern + cleaned_response.split(pattern, 1)[1]
                            break
                    
                    # If we still have reasoning, make a more aggressive cleanup
                    if any(indicator in cleaned_response.lower() for indicator in reasoning_indicators):
                        # Find any staff links
                        staff_link_match = re.search(r'<a href="/staff/\d+" class="staff-link">[^<]+</a>', cleaned_response)
                        availability_match = re.search(r'(?:Available|Unavailable[^\.]*)', cleaned_response)
                        
                        if staff_link_match:
                            staff_link = staff_link_match.group(0)
                            availability = f". Status: {availability_match.group(0)}" if availability_match else ""
                            cleaned_response = f"The best matched staff member is {staff_link}{availability}."
                
                # Always store in history for all request types
                self.add_to_history(user_query, is_user=True)
                self.add_to_history(cleaned_response, is_user=False)
                
                return cleaned_response

            except Exception as api_error:
                logging.error(f"API Error: {str(api_error)}")
                return "I'm having trouble with the AI service. Please try again in a few moments."

        except Exception as e:
            logging.error(f"Error in get_response: {str(e)}")
            return "I'm having trouble processing your request. Please try again."