# Voice Call Integration Setup Guide

This guide walks you through setting up real voice calling capabilities for the HCM Voice Outreach Agent using Twilio, Deepgram, and ElevenLabs.

## 📋 Prerequisites

- Python 3.9+
- Accounts with:
  - **Twilio** (free tier for testing)
  - **Deepgram** (for speech-to-text)
  - **ElevenLabs** (for text-to-speech)

## 🚀 Step-by-Step Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `twilio` - Phone call infrastructure
- `deepgram-sdk` - Speech-to-text
- `elevenlabs` - Text-to-speech
- `flask` - Webhook server
- `python-multipart` - Form data parsing

### 2. Twilio Setup

#### Create a Twilio Account

1. Go to [twilio.com](https://www.twilio.com)
2. Sign up for a free account (includes $20 credit)
3. Verify your phone number
4. Create a phone number (this is your "From" number for calls)

#### Get Your Twilio Credentials

From the Twilio console:
- **Account SID**: Dashboard → Account Info
- **Auth Token**: Dashboard → Account Info
- **Phone Number**: Phone Numbers → Manage Numbers → Active Numbers

#### ⚠️ IMPORTANT: Production HIPAA Compliance

**For production use with patient data (PHI), you MUST upgrade to:**
- **Twilio HIPAA-Compliant Service**
- Visit: https://www.twilio.com/en-us/solutions/healthcare
- Requirements:
  - Business Associate Agreement (BAA)
  - HIPAA-compliant endpoints
  - Encryption: TLS 1.2+
  - Audit logging enabled
  - Data residency in US

The free tier is fine for **testing only**.

### 3. Deepgram Setup (Speech-to-Text)

1. Go to [deepgram.com](https://www.deepgram.com)
2. Sign up for free (includes $250 credits)
3. Navigate to **API Keys**
4. Create a new API key
5. Copy the key

### 4. ElevenLabs Setup (Text-to-Speech)

1. Go to [elevenlabs.io](https://elevenlabs.io)
2. Sign up for free account
3. Navigate to **Account → API Keys**
4. Copy your API key
5. Go to **Voices** and note a voice ID (default: `21m00Tcm4TlvDq8ikWAM`)

### 5. Configure Environment Variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Twilio (free tier for testing)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890

# Deepgram
DEEPGRAM_API_KEY=your_deepgram_key

# ElevenLabs
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# Server
FLASK_PORT=5000
FLASK_HOST=0.0.0.0
```

**Never commit `.env` to version control!** It's in `.gitignore`.

## 🎯 Making Your First Test Call

### Setup

1. Start the Flask voice server:
```bash
python -m hcm_agent.voice_server
```

You should see:
```
 * Running on http://0.0.0.0:5000
```

2. In a **new terminal**, make the test call:

```bash
python make_call.py --phone "+1-704-430-5315"
```

Or interactively:
```bash
python make_call.py
# Follow the prompts
```

### What Happens

1. **Server initiates call**: Flask sends Twilio API request
2. **Twilio dials your phone**: You receive a call from your Twilio number
3. **Patient speaks**: Audio is recorded by Twilio
4. **Deepgram transcribes**: Audio is converted to text
5. **Agent processes**: Claude generates a response
6. **ElevenLabs synthesizes**: Response is converted to speech
7. **Patient hears response**: Audio is played back

## 🔄 Architecture Flow

```
┌─────────────────┐
│  make_call.py   │ ← User initiates call
└────────┬────────┘
         │ HTTP POST /call/initiate
         ↓
┌──────────────────────────┐
│  voice_server.py (Flask) │ ← Webhook server
└────────┬─────────────────┘
         │ Calls Twilio API
         ↓
┌─────────────────┐
│  Twilio         │ ← Makes actual phone call
└────────┬────────┘
         │ Webhook callback
         ↓
┌──────────────────────────┐
│  handle_inbound_call()   │ ← Receives call event
└────────┬─────────────────┘
         │ Records audio
         ↓
┌──────────────────────────┐
│  process_recording()     │ ← Processes audio
├──────────────────────────┤
│ 1. Download from Twilio  │
│ 2. Send to Deepgram      │ ← Transcribe
│ 3. Send to HCMVoiceAgent │ ← Generate response
│ 4. Send to ElevenLabs    │ ← Synthesize
│ 5. Play back to patient  │
└──────────────────────────┘
```

## 📞 API Endpoints

### Initiate a Call

**POST** `/call/initiate`

```bash
curl -X POST http://localhost:5000/call/initiate \
  -H "Content-Type: application/json" \
  -d '{
    "to_number": "+1-704-430-5315",
    "patient_context": {
      "name": "Sarah Martinez",
      "risk_drivers": ["HbA1c > 7.5%", "BP elevated"]
    }
  }'
```

Response:
```json
{
  "status": "initiated",
  "call_sid": "CA1234567890abcdef",
  "patient": "Sarah Martinez",
  "to_number": "+1-704-430-5315"
}
```

### Check Call Status

**GET** `/call/status/<call_sid>`

```bash
curl http://localhost:5000/call/status/CA1234567890abcdef
```

Response:
```json
{
  "sid": "CA1234567890abcdef",
  "status": "completed",
  "duration": "120",
  "start_time": "2026-01-15T10:30:00Z",
  "end_time": "2026-01-15T10:32:00Z",
  "price": "-0.03"
}
```

### Health Check

**GET** `/health`

```bash
curl http://localhost:5000/health
```

## 🧪 Testing

### Test with the Text-Based Agent (No Phone Required)

```bash
# Demo conversation
python test_call.py demo

# Interactive mode
python test_call.py interactive

# Guardrail testing
python test_call.py guardrails
```

### Test Voice Locally (Requires APIs)

```bash
# Start server
python -m hcm_agent.voice_server

# In another terminal, make a call
python make_call.py --phone "+1-704-430-5315"
```

## 🛡️ Security Considerations

### Before Production

- [ ] Upgrade from Twilio free tier to **HIPAA-compliant service**
- [ ] Enable **TLS 1.2+** encryption
- [ ] Set up **AES-256** encryption for call recording
- [ ] Implement **Business Associate Agreements (BAA)** with all vendors
- [ ] Enable **audit logging** for all calls
- [ ] Set up **PHI data minimization** (never log sensitive data)
- [ ] Configure **breach notification** workflows
- [ ] Test **emergency escalation** paths
- [ ] Implement **TCPA compliance** (Do-Not-Call database checks)
- [ ] Review with legal and compliance teams

### Current Free Tier Limitations

- No HIPAA compliance
- Limited to testing/development
- Calls may not be encrypted
- Not suitable for production patient data

## 🐛 Troubleshooting

### "Twilio credentials not configured"

```
Check that .env has:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_PHONE_NUMBER
```

### "Could not connect to voice server"

```
Make sure the Flask server is running:
python -m hcm_agent.voice_server
```

### "No recording URL received"

The patient didn't speak or audio wasn't captured. Check:
- Microphone permissions
- Network connectivity
- Twilio account status

### "Deepgram transcription failed"

- Check DEEPGRAM_API_KEY is valid
- Verify audio format (WAV/MP3)
- Check Deepgram account credits

### "ElevenLabs synthesis failed"

- Check ELEVENLABS_API_KEY is valid
- Verify voice ID exists
- Check ElevenLabs account credits

## 📚 Additional Resources

- [Twilio Docs](https://www.twilio.com/docs)
- [Twilio HIPAA Solution](https://www.twilio.com/en-us/solutions/healthcare)
- [Deepgram Docs](https://developers.deepgram.com)
- [ElevenLabs Docs](https://elevenlabs.io/docs)
- [Flask Documentation](https://flask.palletsprojects.com/)

## 💡 Next Steps

1. ✅ Get credentials from Twilio, Deepgram, ElevenLabs
2. ✅ Fill in `.env` file
3. ✅ Start voice server: `python -m hcm_agent.voice_server`
4. ✅ Make test call: `python make_call.py`
5. ✅ Verify agent responds via phone
6. ⚠️ Before production: Upgrade to Twilio HIPAA service
7. ⚠️ Before production: Review compliance checklist in DESIGN.md
