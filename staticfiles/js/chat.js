// Make sendMessage available before DOM loads
window.sendMessage = null;

document.addEventListener('DOMContentLoaded', function() {
    // Debug log to ensure the script is loading
    console.log('Chat.js loaded');

    // Get DOM elements
    const chatContainer = document.getElementById('chat-container');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const chatbotIcon = document.getElementById('chatbotIcon');
    const closeChat = document.getElementById('close-chat');
    
    // Debug log for elements
    console.log('Send button:', sendButton);
    console.log('Chat input:', chatInput);

    // Get CSRF token
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    // Toggle chat visibility
    function toggleChat() {
        console.log('Toggle chat called');
        chatContainer.classList.toggle('visible');
        if (chatContainer.classList.contains('visible')) {
            chatInput.focus();
        }
    }

    // Bind click events
    chatbotIcon?.addEventListener('click', toggleChat);
    closeChat?.addEventListener('click', toggleChat);
    document.querySelector('.chat-button')?.addEventListener('click', toggleChat);

    // Define sendMessage function
    async function sendMessage(e) {
        // Prevent default if it's a form submission
        if (e) e.preventDefault();
        
        console.log('Send message called');
        const message = chatInput.value.trim();
        if (!message) {
            console.log('Empty message, returning');
            return;
        }

        console.log('Sending message:', message);

        // Add user message immediately
        addMessage(message, true);
        chatInput.value = '';

        try {
            const response = await fetch('/chat-with-ai/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ message })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            console.log('Response received:', data);
            
            if (data.error) {
                addMessage('Sorry, something went wrong.', false);
            } else {
                addMessage(data.response, false);
            }
        } catch (error) {
            console.error('Error:', error);
            addMessage('Sorry, something went wrong.', false);
        }

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Make sendMessage globally available
    window.sendMessage = sendMessage;

    // Bind send button click
    if (sendButton) {
        console.log('Adding click listener to send button');
        sendButton.addEventListener('click', sendMessage);
    }

    // Bind Enter key
    if (chatInput) {
        console.log('Adding keypress listener to chat input');
        chatInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage(e);
            }
        });
    }

    function addMessage(text, isUser) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user' : 'ai'}`;
        if (isUser) {
            messageDiv.textContent = text;
        } else {
            messageDiv.innerHTML = text; // Use innerHTML for AI responses to render HTML
        }
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Voice input handler
    const voiceChatBtn = document.getElementById('voice-chat-btn');
    
    if (voiceChatBtn) {
        voiceChatBtn.addEventListener('click', function() {
            if (!('webkitSpeechRecognition' in window)) {
                alert('Speech recognition is not supported in your browser. Please use Chrome.');
                return;
            }

            const recognition = new webkitSpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';

            recognition.onstart = () => {
                voiceChatBtn.innerHTML = '<i class="fas fa-microphone text-red-500 animate-pulse"></i>';
                voiceChatBtn.classList.add('bg-indigo-50');
                chatInput.placeholder = 'Listening...';
            };

            recognition.onend = () => {
                voiceChatBtn.innerHTML = '<i class="fas fa-microphone"></i>';
                voiceChatBtn.classList.remove('bg-indigo-50');
                chatInput.placeholder = 'Ask about staff...';
            };

            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                chatInput.value = transcript;
                sendMessage();
            };

            recognition.onerror = (event) => {
                console.error('Speech recognition error:', event.error);
                recognition.onend();
            };

            recognition.start();
        });
    }
});
