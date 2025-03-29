# Who's Who App

A Django application for managing staff profiles and departments.

## Environment Variables

Required environment variables:
- `SECRET_KEY`: Django secret key
- `DEBUG`: Set to False in production
- `DATABASE_URL`: PostgreSQL database URL (automatically set by Render)

Optional environment variables:
- `HUGGINGFACE_API_TOKEN`: Your Hugging Face API token (required for AI chat functionality)
- `HUGGINGFACE_MODEL_NAME`: The model name (default: deepseek-ai/DeepSeek-R1-Distill-Qwen-32B)

For initial superuser creation:
- `DJANGO_SUPERUSER_USERNAME`: Admin username
- `DJANGO_SUPERUSER_EMAIL`: Admin email
- `DJANGO_SUPERUSER_PASSWORD`: Admin password

## Deployment on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Use the following settings:
   - Build Command: `./build.sh`
   - Start Command: `gunicorn FYP_whos_who.wsgi:application`
   - Python Version: 3.9
4. Add the required environment variables
5. Deploy the service

## Local Development

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Unix/MacOS: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Run migrations: `python manage.py migrate`
6. Start the development server: `python manage.py runserver`

Note: The AI chat functionality requires a valid Hugging Face API token. Without this token, the chat feature will be disabled but all other app features will work normally.