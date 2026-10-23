"""Role-filtered Markdown retrieval; no embedding/model load per question."""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re

KNOWLEDGE_PATH = Path(__file__).parent / 'knowledge' / 'eflow.md'
STOP = set('the this that with from have does what about can how and for you why who where when which are was has had its your into then do is it to an of on in my me be i a as at by or we please tell explain show need want'.split())
ALIASES = {}
for canonical, variants in {
    'budget': 'budgets budjet budjets budgeting money funding funds fund',
    'task': 'tasks work jobs job', 'subtask': 'subtasks subitem subitems',
    'project': 'projects', 'office': 'offices department departments dept',
    'member': 'members employee employees colleague colleagues staff',
    'invite': 'invites invitation invitations invited inviting',
    'approve': 'approval approvals approved approving approver approvers',
    'review': 'reviews reviewer reviewers reviewing reviewed',
    'settlement': 'settlements settle settled settling liquidation liquidations liquidate',
    'archive': 'archived archiving archives', 'delete': 'deleted deleting deletion remove removed',
    'assign': 'assignment assignments assigned assigning staffing',
    'receipt': 'receipts', 'release': 'releases released releasing disburse disbursement',
    'account': 'accounts', 'complete': 'completed completion completing',
    'reject': 'rejected rejection decline declined', 'return': 'returned returns',
    'stalled': 'stall stuck blocked blocker blockers', 'permission': 'permissions access',
    'dependency': 'dependencies prerequisite prerequisites', 'schedule': 'scheduled scheduling dates date timeline',
    'notification': 'notifications alerts alert', 'report': 'reports reporting',
    'workflow': 'workflows process processes', 'head': 'heads leadership',
    'publish': 'publishing published publication',
    'microphone': 'mic microphones', 'transcribe': 'transcription dictation dictate',
}.items():
    for variant in variants.split(): ALIASES[variant] = canonical

def words(text):
    return {ALIASES.get(word, word) for word in re.findall(r'[a-z][a-z0-9]+', text.lower()) if word not in STOP}

@dataclass(frozen=True)
class Section:
    key: str
    title: str
    roles: frozenset[str]
    tags: frozenset[str]
    facts: tuple[str, ...]
    intents: tuple[frozenset[str], ...] = ()

@lru_cache(maxsize=1)
def _read(path, stamp, size):
    text = Path(path).read_text(encoding='utf-8')
    version = re.search(r'^Version:\s*([\w.-]+)', text, re.M)
    if not version: raise ValueError('Help knowledge needs a version')
    sections, keys = [], set()
    for chunk in text.split('\n## ')[1:]:
        heading, _, body = chunk.partition('\n')
        pieces = [part.strip() for part in heading.split('|')]
        if len(pieces) != 3: raise ValueError('Invalid help knowledge heading')
        key, title, roles = pieces
        if key in keys or not re.fullmatch(r'[a-z][a-z0-9_-]*', key): raise ValueError('Invalid help knowledge ID')
        keys.add(key)
        lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith('<!--')]
        tags = ' '.join(line[9:] for line in lines if line.startswith('Keywords:'))
        intents = tuple(frozenset(words(phrase)) for line in lines if line.startswith('Intents:') for phrase in line[8:].split(';') if words(phrase))
        facts = tuple(line.removeprefix('- ') for line in lines if not line.startswith(('Keywords:', 'Sources:', 'Intents:')))
        if not facts or any(len(fact) > 1000 for fact in facts): raise ValueError('Help passages must be short and complete')
        allowed = frozenset(role.strip() for role in roles.split(','))
        if not allowed <= {'head', 'member', 'accounting_staff', 'admin'}: raise ValueError('Unknown knowledge role')
        sections.append(Section(key, title, allowed, frozenset(words(title + ' ' + tags)), facts, intents))
    return version.group(1), tuple(sections)

def knowledge():
    stat = KNOWLEDGE_PATH.stat()
    return _read(str(KNOWLEDGE_PATH), stat.st_mtime_ns, stat.st_size)

def knowledge_version():
    return knowledge()[0]

def guides(question, role):
    query = words(question)
    eligible = [section for section in knowledge()[1] if role in section.roles]
    # Explicit action cues in the maintained guide disambiguate neighboring
    # workflows (requesting cash versus settling it) before model selection.
    matches = [(len(intent), section.key) for section in eligible for intent in section.intents if intent <= query]
    if matches:
        specificity = max(size for size, _ in matches)
        selected = {key for size, key in matches if size == specificity}
        eligible = [section for section in eligible if section.key in selected]
    documents = [(section, index, text, words(text)) for section in eligible for index, text in enumerate(section.facts)]
    frequency = Counter(word for section, _, _, tokens in documents for word in tokens | section.tags)
    weight = {word: math.log(1 + len(documents) / (1 + frequency[word])) for word in query}
    ranked = []
    for section, index, text, tokens in documents:
        matches = query & (tokens | section.tags)
        if not matches: continue
        score = sum(weight[word] * (2 if word in section.tags else 1) for word in matches)
        score += sum(weight[word] for word in query & tokens)
        ranked.append((score, section.key, index, section, text))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    result, used, counts = [], 0, Counter()
    for _, key, index, section, text in ranked:
        if counts[key] >= 3 or used + len(text) > 3600: continue
        result.append({'id': f'guide:{key}:{index}', 'title': section.title, 'text': text, 'kind': 'guide'})
        counts[key] += 1; used += len(text)
        if len(result) == 8: break
    return result

def combine_facts(live, guidance):
    """Reserve instructions even when project blockers fill the source window."""
    reserved = min(4, len(guidance))
    project = live[:12 - reserved]
    return project + guidance[:12 - len(project)]
