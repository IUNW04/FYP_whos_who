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
        """
        Clean the AI response to ensure:
        - No internal reasoning or step-by-step analysis is present.
        - No repeated expertise/skills.
        - Only relevant staff are mentioned, using the required HTML format.
        - Output is concise and directly answers the user query.
        """
        # Remove all <think>...</think> blocks
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

        # Extract content after FINAL_ANSWER:
        final_answer_match = re.search(r'FINAL_ANSWER:(.*)', text, re.DOTALL)
        if final_answer_match:
            text = final_answer_match.group(1).strip()
        else:
            # If FINAL_ANSWER not found, use the whole text (fallback)
            text = text.strip()

        # Remove any leftover reasoning phrases
        reasoning_patterns = [
            r'(?i)(okay|alright|let me|i will|looking at|based on|considering|i see that|i notice that|i understand that|i can help|i checked|here\'s what|after reviewing|thinking|analyzing|first|initially|to answer this|from my analysis|the user is (?:asking|looking for|trying to find|wants to know)|comparing the staff|among the available staff)[\s,:-]*'
        ]
        for pattern in reasoning_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Remove duplicated skill/expertise phrases
        text = re.sub(r'(with expertise in [^\.]+)\.?\s+\1', r'\1', text, flags=re.IGNORECASE)
        text = re.sub(r'(who specializes in [^\.]+)\.?\s+\1', r'\1', text, flags=re.IGNORECASE)

        # Only keep the first mention of "The best matched staff member is ..."
        best_match_pattern = r'(The best matched staff member is [^\.]+\.)'
        matches = re.findall(best_match_pattern, text)
        if matches:
            text = matches[0] + text.split(matches[0], 1)[-1]
            # Remove any further duplicate "The best matched staff member is ..." phrases
            text = re.sub(best_match_pattern, '', text, count=1)

        # Remove any "_staff" or similar tokens
        text = re.sub(r'_staff', '', text)

        # Remove any remaining duplicated sentences (simple heuristic)
        sentences = []
        seen = set()
        for s in re.split(r'(?<=\.)\s+', text):
            s_clean = s.strip()
            if s_clean and s_clean.lower() not in seen:
                sentences.append(s_clean)
                seen.add(s_clean.lower())
        text = ' '.join(sentences)

        # Remove any leftover HTML or markdown not matching staff link format
        text = re.sub(r'<[^a][^>]*>', '', text)  # Remove all tags except <a ...>

        # Normalize whitespace and periods
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\.{2,}', '.', text)
        text = re.sub(r'\s*\.\s*', '. ', text)

        # Final cleanup: remove any leading/trailing whitespace or periods
        text = text.strip(' .')

        return text + '.'

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

### Staff Selection
- Always mention the best matched staff member, regardless of their availability.
- Only mention an alternative if they are available **and** their roles or skills are relevant to the user's query.
- If the best matched staff member is available, do **not** mention any alternative staff members.
- Do **not** mention unavailable alternative staff members.
- Alternative staff member mentions (if applicable) must be limited to one.

### Output Formatting
- Use the exact HTML format for staff links: `<a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a>`.
- Explicitly include the current availability [Status] of each staff member you mention.
- Do **not** include your thought process, greetings, or internal reasoning in the final output.
- The final output must be a direct and concise answer to the user query.
- Keep responses concise but mention relevant expertise, skills, roles, and other useful information.

### Matching Process
- Use your knowledge to understand relationships between similar skills and terms (e.g., "domain x" relates to "domain x" which relates to "tool x" and staff x has this tool in his skillset therefore he is a match)
- Normalize user queries to account for typos.
- For academic, research, or qualification queries, thoroughly check the staff member's [About] section for accuracy.
- Do **not** make decisions based only on initial information; check all details and fields in all staff profiles.
- Use both exact and semantically related skills/roles for matching.
- If skills are mentioned, only include those most relevant to the user query.
- Be consistent: similar queries should yield the same staff member.
- The best match is the staff member with the most relevant combination of roles and skills.

### Reasoning & Verification
- All analysis, reasoning, and staff comparisons must be wrapped in `<think>...</think>` tags and **not** included in the final output.
- The words `FINAL_ANSWER:` must appear exactly once, after all thinking and before the actual answer.
- Verify your response before returning to ensure accuracy and correctness.

### Real-Time Data
- Always check the real-time availability status of staff members before responding.

### Example output/response: format:
- "The most quyalified person for this request is <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> ([Role]) because [reason]. Their current status is: [Status]."
- Note: Format may change based on the query, but the structure should remain consistent. you MUST ALWAYS use <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> for staff links.
**Summary:**  
- Only the final, concise answer should be output.  
- Absolutely no internal reasoning, greeting, or analysis should appear in the final output.

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