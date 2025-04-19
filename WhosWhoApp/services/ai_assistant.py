import os
import asyncio
import concurrent.futures
from huggingface_hub import InferenceClient

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
        # Remove the greeting
        text = re.sub(r'Hello! I\'m the Who\'s Who AI Staff Finder\. How can I help you today\?', '', text)
        
        # Remove everything between think tags (including the tags)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        
        # Remove any "Okay, let's tackle this question" type phrases
        text = re.sub(r'Okay, let\'s tackle this question:.*?\n', '', text)
        
        # Store staff links and verify names
        staff_links = []
        staff_link_pattern = r'<a href="/staff/(\d+)" class="staff-link">([^<]+)</a>'
        
        def get_correct_name(staff_id):
            try:
                staff = StaffProfile.objects.get(id=staff_id)
                return staff.name
            except StaffProfile.DoesNotExist:
                return '[Unknown Staff]'
        
        # Convert markdown-style links to proper HTML staff links
        markdown_link_pattern = r'\[([^\]]+)\]\(\/staff\/(\d+)\)'
        text = re.sub(markdown_link_pattern, 
                     r'<a href="/staff/\2" class="staff-link">\1</a>', 
                     text)
        
        # Replace any mismatched names in staff links
        def replace_with_correct_name(match):
            staff_id = match.group(1)
            correct_name = get_correct_name(staff_id)
            return f'<a href="/staff/{staff_id}" class="staff-link">{correct_name}</a>'
        
        text = re.sub(staff_link_pattern, replace_with_correct_name, text)
        
        # Expanded list of patterns to remove explanations and thinking
        explanation_patterns = [
            r'Hello! I\'m the Who\'s Who AI Staff Finder\. How can I help you today\?',  # Remove greeting
            r'<think>.*?</think>',  # Remove everything between think tags
            r'Step-by-step explanation:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Understanding the Query:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Here\'s why:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Analysis:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'Let me explain:.*?(?=The best matched staff member|Sorry, from my observation|$)',
            r'\d+\.\s+.*?(?=The best matched staff member|Sorry, from my observation|$)',  # Numbered explanations
            r'\*\*.*?\*\*',  # Remove markdown bold text often used in explanations
            r'Alright,.*?(?=\w+\s+has|$)',                                    
            r'Okay, let\'s figure out.*?(?=\w+\s+has|$)',                    
            r'Looking at the list:.*?(?=\w+\s+has|$)',                       
            r'I\'ll go through.*?(?=\w+\s+has|$)',                          
            r'Looking at the provided staff directory.*?(?=\w+\s+has|$)'     
        ] + [
            f'{starter}.*?(?=The best matched staff member|Sorry, from my observation|$)'
            for starter in [
                '<think>', 'Thinking:', 'Let me analyze', 'Let me see',
                'Let me check', 'Let me look', 'Let me find', 'Let me help',
                'First I need to', 'First, I need to', 'I need to',
                'I will first', 'I will check', 'I will look', 'I will search',
                'I will find', 'To answer this', 'Let\'s look at', 'Let\'s see',
            ]
        ]
        
        # Apply all patterns
        for pattern in explanation_patterns:
            text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Store staff links before cleaning
        staff_links = []
        seen_staff_ids = set()  # Track which staff IDs we've seen
        staff_link_pattern = r'<a href="/staff/(\d+)" class="staff-link">[^<]+</a>'
        
        # Find all staff links but only keep first occurrence for each staff ID
        for match in re.finditer(staff_link_pattern, text):
            staff_id = match.group(1)
            if staff_id not in seen_staff_ids:
                seen_staff_ids.add(staff_id)
                staff_links.append(match.group(0))
                text = text.replace(match.group(0), f'STAFFLINK_{len(staff_links)-1}_PLACEHOLDER')
            else:
                # Remove duplicate staff links
                text = text.replace(match.group(0), '')
        
        # Clean up formatting but preserve staff link placeholders
        text = re.sub(r'(Question:|Answer:|Human:|Assistant:|</think>|First,|Initially,|Finally,|In conclusion,|Therefore,|So,|As a result,)', '', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        # Restore staff links
        for i, link in enumerate(staff_links):
            text = text.replace(f'STAFFLINK_{i}_PLACEHOLDER', link)
        
        # After all other cleaning, remove duplicate sentences
        sentences = text.split('.')
        unique_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence not in unique_sentences:
                unique_sentences.append(sentence)
        text = '. '.join(unique_sentences)
        
        # Ensure response starts with expected patterns and remove duplicates
        if "The best matched staff member" in text:
            parts = text.split("The best matched staff member")
            if len(parts) > 2:  # If there are multiple occurrences
                text = "The best matched staff member" + parts[1]  # Keep only the first occurrence
        elif "Sorry, from my observation" in text:
            if not text.strip().startswith("Sorry, from my observation"):
                text = "Sorry, from my observation" + text.split("Sorry, from my observation")[1]
        
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
For example:
<think>
Hello! I'm the Who's Who AI Staff Finder. How can I help you today?
Analyzing the query...
[Your analysis here]
</think>
[Your final clean response here]

Here is our staff directory:

{staff_info}


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
IMPORTANT: You MUST  "<think>" followed by your reasoning process, then "</think>" before providing your final answer.your final output however must not include the <think> tags or your thought process.
- IMPORTANT: For staff mentions you MUST use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a>
- IMPORTANT: include the current availability status of each staff member you mention in your response.
- IMPORTANT: you must NOT simply make deciscions based on the intital information you see ragarding staff members, you MUST make a thotough check of ALL the information WITHIN the staff members profiles to ensure you are making the most accurate and correct decision possible.
- IMPORTANT: verify your response before returning it to ensure you are not making any mistakes or errors in your response.
- 'THINKING' SHOULD BE DONE IN THE BACKGROUND AND NOT INCLUDED IN THE FINAL OUTPUT
- ANALYSIS, REASONING AND STAFF COMPARISONS SHOULD BE DONE IN THE BACKGROUND AND NOT INCLUDED IN THE FINAL OUTPUT
- FINAL OUTPUT MUST BE A DIRECT AND CONCISE ANSWER TO THE USER QUERY
- be concise in your responses, make subsequet thurough checks of ALL details and ALL fields within ALL staff profiles before making your response to ensure accuracy and make sure you use use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> format for staff links in every response where you mention staff member/s.

Question: {user_query} [/INST]"""

    def get_response(self, user_query):
        if not self.client:
            return "AI assistant is currently unavailable. Please contact the administrator to set up the Hugging Face API token."

        try:
            all_staff = StaffProfile.objects.all()
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

            recent_context = None  # Remove context for non-email requests
            prompt = self.generate_prompt(user_query, staff_info, recent_context, is_email_request)

            try:
                response = self._make_api_request(prompt)
                generated_text = ""
                for chunk in response:
                    if isinstance(chunk, str):
                        generated_text += chunk
                    else:
                        generated_text += chunk.get("generated_text", "")

                cleaned_response = self.clean_response(generated_text)
                
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
