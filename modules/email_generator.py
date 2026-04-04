"""
Personalized Outreach Email Generator
--------------------------------------
Generates a personalized email inviting a YouTube creator to Bilibili,
using channel data, AI report, and video transcripts.

Uses Claude Sonnet (exception to Haiku-only rule — user approved for email quality).

Public API:
    generate_email(channel_data: dict, report_data: dict, transcripts: list) -> dict
"""

import os
import re
import json


def generate_email(channel_data: dict, report_data: dict, transcripts: list = None) -> dict:
    """
    Generate a personalized Bilibili invitation email for a YouTube creator.

    Args:
        channel_data: Channel info from scraper (name, handle, subscribers, description, etc.)
        report_data:  AI report v2 result (niche, themes, audience, style, key_insight, tags)
        transcripts:  List of transcript excerpts (optional, for deeper personalization)

    Returns:
        {'subject': str, 'body': str}
        or {'error': str}
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {'error': 'ANTHROPIC_API_KEY not set'}

    prompt = _build_prompt(channel_data, report_data, transcripts)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return {'error': 'Invalid AI response'}
        data = json.loads(match.group())
        subject = data.get('subject', '').strip()
        body = data.get('body', '').strip()
        if not subject or not body:
            return {'error': 'Empty email generated'}
        return {'subject': subject, 'body': body}
    except Exception as e:
        return {'error': f'Email generation failed: {str(e)}'}


def _build_prompt(channel_data: dict, report_data: dict, transcripts: list = None) -> str:
    # Channel info
    lines = ['=== Creator Profile ===']
    for field, label in [
        ('name', 'Name'),
        ('handle', 'Handle'),
        ('subscribers', 'Subscribers'),
        ('views', 'Total views'),
        ('videos', 'Video count'),
        ('location', 'Location'),
        ('description', 'About'),
    ]:
        val = channel_data.get(field)
        if val:
            lines.append(f'{label}: {val}')

    # AI report
    report = report_data.get('report', {})
    if report:
        lines.append('\n=== AI Analysis ===')
        for field, label in [
            ('content_language', 'Content Language'),
            ('niche', 'Niche'),
            ('content_themes', 'Themes'),
            ('audience', 'Audience'),
            ('content_style', 'Style'),
            ('brand_fit', 'Brand Fit'),
            ('key_insight', 'Key Insights'),
        ]:
            val = report.get(field)
            if val:
                lines.append(f'{label}: {val}')

    tags = report_data.get('tags', [])
    if tags:
        lines.append(f'Tags: {", ".join(tags)}')

    # Transcript excerpts for tone understanding
    if transcripts:
        lines.append('\n=== Sample Transcript Excerpts ===')
        for i, t in enumerate(transcripts[:3], 1):
            if t and len(t.strip()) > 20:
                lines.append(f'Excerpt {i}: {t[:500]}')

    context = '\n'.join(lines)

    # Detect if creator likely speaks a non-English language
    lang = report.get('content_language', 'English')

    return f"""You are writing a personalized outreach email to invite a YouTube creator to Bilibili.

{context}

TASK: Write a short, personalized email inviting this creator to also share their content on Bilibili.

RULES:
- Write the email in the creator's content language ({lang}). If {lang} is English or Unknown, write in English.
- The email must feel personal — reference specific things about their content, style, or niche.
- Tone: warm, genuine, motivating. Like a message from someone who actually watches their content.
- Do NOT sound like corporate marketing or a mass email template.
- Do NOT use excessive flattery or hype words.
- Keep it concise — 150-250 words for the body.
- The goal is to make the creator curious and excited about reaching Bilibili's audience.
- Mention how their specific content style/niche could resonate with Bilibili's audience.
- End with a soft, low-pressure call to action (not "sign up now" — more like "would love to chat about this").
- Subject line: short, personal, intriguing (not salesy).

Respond ONLY with valid JSON:
{{
  "subject": "...",
  "body": "..."
}}"""
