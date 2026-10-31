"""Provider-neutral AI analysis using OpenAI-compatible chat endpoints."""
import requests


def analyze(prompt, context='', endpoint='https://api.openai.com/v1/chat/completions', api_key='', model='gpt-4o-mini'):
    if not api_key:
        return {'success': False, 'error': 'AI API key is required'}
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'You are an SEO technical analyst. Return concise actionable findings.'},
            {'role': 'user', 'content': f'{prompt}\n\nCrawl context:\n{context[:100000]}'},
        ],
        'temperature': 0.2,
    }
    response = requests.post(endpoint, json=payload, headers={'Authorization': f'Bearer {api_key}'}, timeout=60)
    response.raise_for_status()
    data = response.json()
    choices = data.get('choices', [])
    return {'success': True, 'text': choices[0].get('message', {}).get('content', '') if choices else '', 'raw': data}
