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
            "stream": False,  # Ensure we get complete response
            "do_sample": True,
            "top_p": 0.9,
        }
        
        model_configs = {
            "deepseek": {
                "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
                "temperature": 0.31,
                "max_new_tokens": 150,  # Keep this higher since response is getting cut
                "repetition_penalty": 1.1,
                "timeout": 20  # Increased timeout to ensure complete response
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
                except concurrent.futures.TimeoutError:
                    logging.error(f"Timeout with {model_type} model")
                    raise
                except Exception as e:
                    logging.error(f"Error with {model_type} model: {str(e)}")
                    raise

        try:
            logging.info("Attempting DeepSeek model")
            return try_model("deepseek")
        except Exception:
            logging.info("Switching to Mistral model")
            return try_model("mistral")



    def clean_response(self, text):
        # Only clean obvious formatting issues
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Ensure response starts with expected patterns
        if not (text.startswith("The most qualified person") or text.startswith("Sorry, from my observation")):
            if "The most qualified person" in text:
                text = "The most qualified person" + text.split("The most qualified person")[1]
            elif "Sorry, from my observation" in text:
                text = "Sorry, from my observation" + text.split("Sorry, from my observation")[1]
        
        # Complete any cut-off staff links
        staff_link_pattern = r'<a href="/staff/(\d+)" class="staff-link">([^<]+)</a>'
        if text.count('<a href="/staff/') > text.count('</a>'):
            incomplete_link_match = re.search(r'<a href="/staff/(\d+)" class="staff-link">([^<]*?)$', text)
            if incomplete_link_match:
                staff_id = incomplete_link_match.group(1)
                try:
                    staff = StaffProfile.objects.get(id=staff_id)
                    text = text.rstrip() + f"{staff.name}</a>"
                except StaffProfile.DoesNotExist:
                    pass

        return text

    def generate_prompt(self, user_query, staff_info, context_text=None, is_email_request=False):

        if is_email_request:
            return f"""<s>[INST] Recent conversation context:
{context_text}

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
            return f"""<s>[INST] Here is our staff directory:

{staff_info}

STRICT RESPONSE FORMAT REQUIREMENTS:

- ALWAYS MENTION THE BEST MATCHED STAFF REGARDLESS OF THEIR AVAILABILITY STATUS
- ONLY NAME AN ALTERNATIVE IF THEY ARE AVAILABLE, AND THEIR ROLES OR SKILLS ARE RELATED TO THE USERS QUERY
- MUST NOT MENTION ANY MATCHED ALTERNATIVE STAFF MEMBERS IF THEY ARE UNAVAILABLE
- THE MENTION OF BEST MATCHED STAFF IS NOT DEPENDANT ON AVAILABILITY
- USE THE EXACT HTML FORMAT PROVIDED BELOW FOR STAFF LINKS
- IN YOUR RESPONSE DO NOT INCLUDE YOUR THOUGHT PROCESS
- KEEP YOUR RESPONSE CONCISE 
- USERS MAY MAKE TYPOS SO TRY TO NORMALISE THE TEXT OF THE USER QUERY AS MUCH AS POSSIBLE


Important matching guidelines:
- Use your knowledge to understand relationships between similar skills and terms (e.g., "domain x” relates to "domain x” which relates to “tool x” and staff x has this tool in his skillset therefore he is a match)
- Look for both exact matches and semantically related skills in staff profiles
- Consider the broader context of roles and how they relate to the requested expertise
- ONLY mention an alternative if they are available and their skills or roles are related to the user query. when mentioning an alternative staff member, make sure to ONLY mention the skills of theirs that are MOST relevant to the user query. If their skills are not directly or strongly related to the user query, do not mention that staff member as an alternative at all.
- The best match is the staff member whose skills and roles are most relevant to the user query. If its close, choose the staff member with the most skills related to the user query OR the staff member with the most relevant roles related to the user query. Put yourself in the users shoes and think about who would be the best person to help them. roles and skills both compliment each other so consider both when making a decision. best match usually has a good combination of relevant roles and skills.
- If you mention skills as part of the reason for best match or alternative (if any), make sure to ONLY mention their skills that are MOST relevant to the user query.
- Be consistant with your matching. Different phrasing of the same query should result in the same staff member being mentioned. 
Format your concise responses using these exact patterns:

1. For staff mentions, use: <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a>

2. If best match is unavaible mention them however also mention the alternative if there is one AND if they are available):
"The most qualified person for this request is <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> ([Role]) because [reason]. Their current status is: [Status]. However, since they are unavailable, <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> ([Role]) can help because [reason]. Their status is: [Status]."

3. If best match is available AND if no alternatives OR if there are no alternatives that are available):
"The most qualified person for this request is <a href="/staff/{{staff_id:NUMBER}}" class="staff-link">[Name]</a> ([Role]) because [reason]. Their current status is: [Status]."

4. When no one has any skills or roles that match the user query in any way:
"Sorry, from my observation, I do not see anyone in the database that can help you with your query, please look for external help."

Question: {user_query} [/INST]"""

    def get_response(self, user_query):
        if not self.client:
            return "AI assistant is currently unavailable. Please contact the administrator to set up the Hugging Face API token."

        try:
            # Get staff info and generate prompt
            staff_info = self.get_staff_info()
            email_phrases = ['write an email', 'send an email', 'draft an email', 'compose an email']
            is_email_request = any(phrase in user_query.lower() for phrase in email_phrases)

            logging.debug(f"User Query: {user_query}, Detected Email Request: {is_email_request}")

            recent_context = None
            prompt = self.generate_prompt(user_query, staff_info, recent_context, is_email_request)

            # Make API request with consistent parameters
            response = self._make_api_request(prompt)
            
            # Log raw response for debugging
            logging.debug(f"Raw API response: {response}")

            # Process the response
            generated_text = ""
            if isinstance(response, str):
                generated_text = response
            else:
                generated_text = response.get("generated_text", "")

            # Log generated text before cleaning
            logging.debug(f"Generated text before cleaning: {generated_text}")

            # Clean the response without modifying core content
            cleaned_response = self.clean_response(generated_text)
            
            # Log cleaned response
            logging.debug(f"Cleaned response: {cleaned_response}")

            # Only store history for email requests
            if is_email_request:
                self.add_to_history(user_query, is_user=True)
                self.add_to_history(cleaned_response, is_user=False)

            return cleaned_response

        except Exception as e:
            logging.error(f"Error in get_response: {str(e)}")
            return "I encountered an error while processing your request. Please try again."

    def get_staff_info(self):
        """Get formatted staff information for the prompt"""
        try:
            staff_profiles = StaffProfile.objects.select_related('department').all()
            staff_info = []
            
            for staff in staff_profiles:
                status = self.get_availability_status(staff)
                skills = staff.get_skills()  # Using the get_skills method from StaffProfile
                roles = staff.get_roles()    # Using the get_roles method from StaffProfile
                
                staff_entry = (
                    f"Staff ID: {staff.id}\n"
                    f"Name: {staff.name}\n"
                    f"Role: {', '.join(roles)}\n"
                    f"Department: {staff.department.name if staff.department else 'Not specified'}\n"
                    f"Skills: {', '.join(skills)}\n"
                    f"Role Description: {staff.bio if staff.bio else 'No role description provided'}\n"
                    f"Status: {status}\n"
                    "---"
                )
                staff_info.append(staff_entry)
            
            return "\n".join(staff_info)
        except Exception as e:
            logging.error(f"Error getting staff info: {str(e)}")
            return "Error retrieving staff information"
