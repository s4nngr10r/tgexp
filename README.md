# Telegram Auto-Responder Bot

This application allows you to manage multiple Telegram sessions and automatically respond to messages in groups and channels using DeepSeek's AI API.

## Features

- **Multiple Session Management**: Create and manage multiple Telegram accounts
- **Channel Synchronization**: Ensure all accounts are subscribed to the same channels
- **AI-Powered Responses**: Automatically generate engaging responses to messages using DeepSeek AI
- **Session Persistence**: Save and reuse session credentials
- **Environment Configuration**: Easy configuration through environment variables
- **Customizable AI Personalities**: Configure different personality styles and formality levels
- **Context-Aware Responses**: Adapts to channel topics and discussion context

## Setup

1. Install required packages:
   ```
   pip install -r requirements.txt
   ```

2. Configure your environment:
   - Edit the `.env` file to set your DeepSeek API key and other options
   - Alternatively, you can set these through the application menu

3. Run the application:
   ```
   python main.py
   ```

4. Follow the interactive menu to:
   - Create new sessions
   - Load existing sessions
   - View and manage channels
   - Set your DeepSeek API key
   - Start monitoring

## Environment Configuration

You can configure the application using the `.env` file:

```
# DeepSeek API key (required for AI response generation)
DEEPSEEK_API_KEY=your_api_key_here

# Optional: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOGGING_LEVEL=INFO

# Optional: Response generation parameters
AI_TEMPERATURE=0.7
AI_MAX_TOKENS=100

# Optional: AI personality and style settings
# Personality options: default, friendly, witty, expert, provocative
AI_PERSONALITY=default

# Formality level options: casual, neutral, formal
AI_FORMALITY=casual
```

## AI Personality Customization

You can customize the AI's personality and formality level through environment variables:

### Personality Types
- **default**: Balanced personality with moderate emotional expression
- **friendly**: Supportive, agreeable, and positive in all interactions
- **witty**: Light sarcasm and humor, playful responses
- **expert**: Demonstrates deeper knowledge and competence in discussions
- **provocative**: Politely challenges claims and encourages debate

### Formality Levels
- **casual**: Informal, conversational language with slang and everyday expressions
- **neutral**: Balanced formality suitable for most contexts
- **formal**: More proper language with minimal slang and correct grammar

The bot also adapts its responses based on the channel's topic, automatically detecting categories like technology, politics, and entertainment.

## DeepSeek API Key

You'll need a DeepSeek API key to use the response generation feature. You can get one from [DeepSeek's website](https://deepseek.com/). Set it in the `.env` file or through menu option 5.

## Channel Synchronization

To synchronize channels across all sessions, create a JSON file with the list of channel links in this format:

```json
[
  "https://t.me/channelname",
  "https://t.me/+privateChannelInviteCode",
  "https://t.me/joinchat/oldPrivateChannelCode"
]
```

Then use menu option 4 to load and sync these channels.

## How It Works

The system:
1. Monitors all messages in groups and channels where your accounts are members
2. When a message is detected, it:
   - Extracts the channel name, description, and message text
   - Identifies the channel topic to adapt the conversational style
   - Sends this data to DeepSeek AI with a prompt to generate an engaging response
   - Posts the generated response back to the group/channel

The responses are designed to be:
- Contextually relevant to the channel topic
- Engaging to encourage discussion
- Brief (under 20 words)
- In Russian with appropriate conversational style
- Personality-adjusted based on your configuration

## Required Telegram API Credentials

To use this application, you'll need:
- Telegram API ID
- Telegram API Hash
- Phone number

You can get your API ID and hash from [my.telegram.org](https://my.telegram.org/).

## License

This project is for educational purposes only. Use responsibly and in accordance with Telegram's Terms of Service. 