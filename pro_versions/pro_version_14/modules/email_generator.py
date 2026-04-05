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
        subject = data.get('subject', '').strip().replace('—', '-')
        body = data.get('body', '').strip().replace('—', '-')
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

    return f"""You are a Bilibili partnership representative writing a professional outreach email to a YouTube creator.

{context}

TASK: Write a professional, personalized email inviting this creator to expand their content to Bilibili.

WRITING STYLE:
- Study the transcript excerpts and creator's style carefully. Mirror the creator's own tone, vocabulary, and communication patterns in the email. If they are casual and witty, reflect that subtly. If they are analytical and precise, match that register. The email should feel like it was written by someone who genuinely understands how they communicate.
- Write the ENTIRE email in the creator's content language ({lang}). If {lang} is Unknown, write in English.

TONE:
- Professional and respectful, but approachable. Think "business email from someone friendly", not "fan letter" or "corporate template".
- Do NOT be overly familiar, enthusiastic, or casual. No excessive compliments, no hype words, no exclamation marks overuse.
- Be confident and straightforward. State the opportunity clearly without overselling.

PERSONALIZATION:
- Show that you have genuinely reviewed their channel. Reference their content area, approach, or what makes their channel distinctive.
- Do NOT cite specific video titles, quotes, or timestamps. The personalization should feel natural and observant, not like a checklist. The reader should think "this person actually looked at my channel" without feeling like their content was dissected.
- Briefly connect their content strengths to why Bilibili's audience would appreciate them.

STRUCTURE:
- Short professional greeting
- 1-2 sentences showing you know their work (subtle, not forced)
- The opportunity: Bilibili has a large audience interested in their niche
- What you can offer (support with localization, promotion, onboarding)
- Soft call to action: suggest a brief call or reply, no pressure
- Professional sign-off

CONSTRAINTS:
- 150-250 words for the body
- NEVER use the em dash character. Use a comma, period, or hyphen instead.
- No marketing buzzwords, no "exciting opportunity", no "we'd be thrilled"
- Subject line: short, professional, relevant to their niche (not clickbait)

Respond ONLY with valid JSON:
{{
  "subject": "...",
  "body": "..."
}}"""
