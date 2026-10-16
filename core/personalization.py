"""Inspectable topic + opportunity intent matching. This is not semantic AI."""
import re
from dataclasses import dataclass, asdict

VERSION = 'interest-intent-v1'


@dataclass
class Decision:
    relevance: str
    reasons: list[dict]
    matched_interests: list[str]

    def to_dict(self):
        return asdict(self)


def occurrence(text, term):
    if not term.strip():
        return None
    # ASCII word boundaries stop `AI` matching `email` / `paid`.
    escaped = re.escape(term.strip())
    pattern = r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])' if term.isascii() and term.replace(' ', '').isalnum() else escaped
    return re.search(pattern, text, re.I)


def evidence(text, match):
    start = max(0, text.rfind('\n', 0, match.start()) + 1)
    start = max(start, match.start() - 60)
    return text[start:min(len(text), match.end()+90)].strip()


def decide(item, profile):
    text = item.get('title', '') + '\n' + item.get('body', '')
    reasons=[]; high=[]; partial=[]
    for interest in profile.interests:
        matches=[(term, occurrence(text,term)) for term in interest.terms]
        matches=[(t,m) for t,m in matches if m]
        if not matches:
            continue
        intent_matches=[v for v in interest.intents if occurrence(text,v)]
        avoided=[v for v in interest.avoid if occurrence(text,v)]
        matched=not avoided and (not interest.intents or bool(intent_matches))
        (high if matched else partial).append(interest.name)
        reasons.append({'interest':interest.name,'term':matches[0][0],
                        'evidence':evidence(text,matches[0][1]),
                        'intent':intent_matches[:3], 'conflicts':avoided[:3],
                        'basis':'inferred','explanation': '方向及机会意图匹配，适用资格仍需核实。' if matched else '仅方向词匹配，机会意图或适用性不足，保持待核实。'})
    # Backward compatible legacy strings are weaker than an explicit topic+intent.
    if not profile.interests:
        for word in profile.research_interests+profile.skills+profile.goals+profile.opportunities:
            m=occurrence(text,word)
            if m:
                high.append(word)
                reasons.append({'interest':word,'term':word,'evidence':evidence(text,m),'intent':[],
                                'conflicts':[],'basis':'inferred','explanation':'仅显式词匹配，不能证明具备参与资格。'})
    disliked=[v for v in profile.uninterested if occurrence(text,v)]
    relevance='high' if high else ('medium' if partial else ('low' if disliked else 'unknown'))
    if disliked and high:
        relevance='medium'  # Positive/negative conflict is not silently resolved.
        reasons.append({'interest':'偏好冲突','term':disliked[0], 'evidence':evidence(text,occurrence(text,disliked[0])),
                        'intent':[],'conflicts':disliked,'basis':'inferred','explanation':'同时命中关注和排除项，需人工确认。'})
    return Decision(relevance,reasons,high+partial)
