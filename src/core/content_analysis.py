"""Dependency-light content analysis helpers."""
import re
from collections import Counter


STOPWORDS = set('the and or but for with this that from into have has was are not una uno una gli le dei del della per con che non una'.split())


def analyze_content(soup, selector=None):
    """Return content-area text, readability, n-grams and heuristic findings."""
    area = None
    if selector:
        try:
            area = soup.select_one(selector)
        except Exception:
            area = None
    area = area or soup.find('main') or soup.find('article') or soup.find('body') or soup
    text = ' '.join(area.get_text(' ', strip=True).split())
    words = re.findall(r"[A-Za-zÀ-ÿ0-9']+", text.lower())
    sentences = [part for part in re.split(r'[.!?]+', text) if part.strip()]
    syllables = sum(_syllable_count(word) for word in words)
    word_count = len(words)
    sentence_count = max(len(sentences), 1)
    avg_words = word_count / sentence_count if sentence_count else 0
    avg_syllables = syllables / max(word_count, 1)
    readability = round(206.835 - (1.015 * avg_words) - (84.6 * avg_syllables), 2) if word_count else 0

    bigrams = Counter(' '.join(words[index:index + 2]) for index in range(max(0, word_count - 1)))
    trigrams = Counter(' '.join(words[index:index + 3]) for index in range(max(0, word_count - 2)))
    repeated = [phrase for phrase, count in bigrams.most_common(20) if count > 1 and not all(word in STOPWORDS for word in phrase.split())]
    grammar = []
    if text and not re.search(r'[.!?]$', text):
        grammar.append({'rule': 'sentence-final-punctuation', 'message': 'Content does not end with sentence punctuation'})
    if re.search(r'\s{2,}', text):
        grammar.append({'rule': 'multiple-spaces', 'message': 'Content contains repeated whitespace'})
    spelling = []
    for word, count in Counter(words).items():
        if count > 2 and len(word) > 4 and re.search(r'(.)\1\1', word):
            spelling.append({'word': word, 'count': count, 'rule': 'repeated-character'})
    return {
        'content_area': area.name if getattr(area, 'name', None) else 'document',
        'content_text': text[:100000],
        'readability': {'flesch_score': readability, 'words': word_count, 'sentences': sentence_count},
        'n_grams': {'bigrams': [{'text': p, 'count': c} for p, c in bigrams.most_common(20)],
                    'trigrams': [{'text': p, 'count': c} for p, c in trigrams.most_common(20)]},
        'grammar': grammar,
        'spelling': spelling,
        'repeated_phrases': repeated,
    }


def _syllable_count(word):
    groups = re.findall(r'[aeiouyàèéìòù]+', word.lower())
    return max(1, len(groups))
