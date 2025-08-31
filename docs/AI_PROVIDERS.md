# AI Provider Configuration Guide

The Migration Service supports multiple AI providers with intelligent fallback to ensure reliable AI assistance while optimizing costs.

## 🎯 Priority Order (Cost Optimized)

The system is configured to prioritize **free local models first**, then **paid APIs in order of cost efficiency**:

1. **Local Hugging Face Model** (FREE) - Always tried first
2. **XAI Grok** (Paid - Competitive pricing)
3. **Anthropic Claude** (Paid - Moderate pricing) 
4. **OpenAI GPT** (Paid - Higher pricing)
5. **Hugging Face API** (Paid - Highest inference pricing)

## 🔐 Security & Environment Variables

**CRITICAL**: All API keys are loaded from environment variables for security. Never hard-code API keys in configuration files!

### Setting Up Environment Variables

1. Copy the sample environment file:
   ```bash
   cp .env.sample .env
   ```

2. Set secure file permissions:
   ```bash
   chmod 600 .env
   ```

3. Edit `.env` and uncomment/set only the API keys you have:
   ```bash
   # Only set the APIs you want to use
   XAI_API_KEY=xai-your-actual-api-key-here
   ANTHROPIC_API_KEY=sk-ant-api03-your-actual-key-here
   OPENAI_API_KEY=sk-proj-your-actual-key-here
   # HUGGINGFACE_API_KEY=hf_your-token-here  # Optional, paid service
   ```

## 🏃‍♂️ Getting Started (Minimal Setup)

### Option 1: Free Local Model Only
Just run the system! No API keys required. The local Hugging Face model will handle all requests.

```bash
python -m core.main
```

### Option 2: Add One Paid API (Recommended)
Get an API key from any one provider for backup:

```bash
# Add to your .env file:
export XAI_API_KEY="your-xai-key"
# OR
export ANTHROPIC_API_KEY="your-anthropic-key" 
# OR
export OPENAI_API_KEY="your-openai-key"
```

### Option 3: Full Multi-Provider Setup
Set up multiple providers for maximum reliability and feature coverage.

## 🔑 Getting API Keys

### XAI (Grok) - Recommended First Paid Option
- **Website**: https://console.x.ai/
- **Pricing**: Competitive, good for general queries
- **Features**: OpenAI-compatible API, witty responses
- **Environment Variable**: `XAI_API_KEY`

### Anthropic (Claude) - Recommended for Complex Tasks
- **Website**: https://console.anthropic.com/
- **Pricing**: Moderate, excellent for analysis
- **Features**: High-quality reasoning, ethical AI
- **Environment Variable**: `ANTHROPIC_API_KEY`

### OpenAI (GPT) - Industry Standard
- **Website**: https://platform.openai.com/api-keys
- **Pricing**: Higher, but widely supported
- **Features**: Function calling, broad capabilities
- **Environment Variable**: `OPENAI_API_KEY`

### Hugging Face API - Advanced Users Only
- **Website**: https://huggingface.co/settings/tokens
- **Pricing**: Highest for inference APIs
- **Features**: Access to many specialized models
- **Environment Variable**: `HUGGINGFACE_API_KEY`
- **Note**: Only enable if you need specific HF models

## ⚙️ Advanced Configuration

### Customizing Provider Priority

You can override the default priority order:

```bash
# In your .env file:
AI_PROVIDERS=huggingface_local,anthropic,openai,xai,huggingface_api
```

### Model Selection

Customize which models each provider uses:

```bash
# Local model (free)
AI_LOCAL_MODEL=microsoft/DialoGPT-medium

# Provider-specific models
XAI_MODEL=grok-beta
ANTHROPIC_MODEL=claude-3-haiku-20240307  # Faster, cheaper
OPENAI_MODEL=gpt-3.5-turbo
HUGGINGFACE_MODEL=microsoft/DialoGPT-large
```

### API Endpoints

Customize API endpoints if needed:

```bash
XAI_BASE_URL=https://api.x.ai/v1
HF_BASE_URL=https://api-inference.huggingface.co
```

## 🛡️ Fallback Behavior

The system automatically handles failures:

1. **Primary**: Try local Hugging Face model
2. **Fallback 1**: Try XAI Grok (if configured)
3. **Fallback 2**: Try Anthropic Claude (if configured)  
4. **Fallback 3**: Try OpenAI GPT (if configured)
5. **Last Resort**: Try Hugging Face API (if configured)

If all providers fail, you'll get a clear error message.

## 💰 Cost Management

### Free Tier Usage
- Local Hugging Face model is completely free
- No internet required after initial model download
- Runs on your hardware (CPU/GPU)

### Paid API Best Practices
1. **Start small**: Get one API key (XAI recommended)
2. **Set limits**: Configure usage limits in provider dashboards
3. **Monitor usage**: Check your API usage regularly
4. **Use billing alerts**: Set up cost alerts
5. **Rotate keys**: Change API keys periodically

### Cost Optimization Tips
- **Local first**: Keep `huggingface_local` as first priority
- **Remove expensive APIs**: Comment out `HUGGINGFACE_API_KEY` if not needed
- **Choose cheaper models**: Use `claude-3-haiku` instead of `claude-3-sonnet`
- **Set token limits**: Reduce `max_tokens` in responses

## 🔍 Monitoring & Logging

The system logs which provider responds to each query:

```bash
tail -f logs/migration_service.log | grep "Successfully got response"
```

Example log output:
```
INFO: Successfully got response from huggingface_local
INFO: Provider huggingface_local failed: Model not loaded, trying next...  
INFO: Successfully got response from xai
```

## 🚀 Performance Optimization

### Local Model Performance
- **GPU acceleration**: Install CUDA for faster local inference
- **Model selection**: Smaller models (DialoGPT-medium) are faster
- **Memory management**: Larger models need more RAM

### API Performance
- **Response times**: XAI and OpenAI typically fastest
- **Reliability**: Anthropic very reliable, good uptime
- **Rate limits**: Respect each provider's rate limits

## 🛠️ Troubleshooting

### Common Issues

#### "No AI providers available"
- **Cause**: No API keys set and local model failed to load
- **Solution**: Set at least one API key in `.env`

#### "Local model error: Model not initialized"
- **Cause**: Insufficient memory or missing dependencies
- **Solution**: Install `torch` and ensure adequate RAM

#### "XAI API error: Unauthorized"
- **Cause**: Invalid or missing API key
- **Solution**: Check your XAI console for correct key format

#### "Provider X failed: Rate limit exceeded"
- **Cause**: Too many requests to the API
- **Solution**: Wait and retry, or check your API usage limits

### Debug Mode

Enable debug logging:
```bash
LOG_LEVEL=DEBUG
```

### Testing Configuration

Test your setup:
```bash
python -c "from core.config import get_settings; s = get_settings(); print('Available providers:', s.ai.ai_providers)"
```

## 🔒 Security Checklist

- [ ] API keys stored in environment variables only
- [ ] `.env` file has proper permissions (`chmod 600 .env`)
- [ ] `.env` file is in `.gitignore`
- [ ] Different API keys for dev/staging/production
- [ ] API keys rotated regularly
- [ ] Usage monitoring enabled
- [ ] Billing alerts configured

## 🌟 Recommended Setups

### Beginner (Free)
```bash
# No configuration needed!
# Just use local model
```

### Small Team (Budget-Conscious)
```bash
XAI_API_KEY=your-xai-key-here
AI_PROVIDERS=huggingface_local,xai
```

### Production Environment
```bash
XAI_API_KEY=your-xai-key-here
ANTHROPIC_API_KEY=your-anthropic-key-here
OPENAI_API_KEY=your-openai-key-here
AI_PROVIDERS=huggingface_local,xai,anthropic,openai
```

### Research/Development
```bash
# All providers for maximum flexibility
XAI_API_KEY=your-xai-key-here
ANTHROPIC_API_KEY=your-anthropic-key-here
OPENAI_API_KEY=your-openai-key-here
HUGGINGFACE_API_KEY=your-hf-token-here
```

The system is designed to work great with any combination of providers, from free local-only to full multi-provider setups!
