"""Fixed, hand-labeled fictional evaluation; no network or real database access."""
import json
from collections import Counter
from pathlib import Path

from core.analysis import rules
from core.profile import Profile
from core.smart import route


def evaluate():
    data = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/analysis_labeled.json').read_text(encoding='utf-8'))
    samples = data['samples']
    counts = Counter(); confusion = Counter(); errors=[]; per_split={}; reviewed=Counter()
    reviewed_ids=set(data.get('human_review',{}).get('ids',[]))
    for sample in samples:
        item = {'title':sample['title'], 'body':sample['body'], 'source':'test'}
        value = rules(item, Profile())
        counts['category'] += value.category == sample['category']
        counts['deadline'] += value.deadline.value == sample['deadline']
        counts['key'] += any(c.text == sample['key'] for c in value.key_items)
        counts['mandatory_total'] += sample['mandatory']
        counts['mandatory_recalled'] += sample['mandatory'] and route(item,value,'ok',Profile()) == 'immediate'
        counts['false_important'] += not sample['mandatory'] and value.importance == 'high'
        counts['known_deadlines'] += sample['deadline'] is not None
        counts['predicted_deadlines'] += value.deadline.value is not None
        counts['deadline_true_positive'] += sample['deadline'] is not None and sample['deadline'] == value.deadline.value
        confusion[(sample['category'],value.category)]+=1
        split=per_split.setdefault(sample['split'],{'n':0,'category_correct':0})
        split['n']+=1;split['category_correct']+=value.category==sample['category']
        if value.category!=sample['category'] or value.deadline.value!=sample['deadline']:
            errors.append({'id':sample['id'],'expected_category':sample['category'],'predicted_category':value.category,'deadline_correct':value.deadline.value==sample['deadline']})
        if sample['id'] in reviewed_ids:
            reviewed['n']+=1
            reviewed['category']+=value.category==sample['category']
            reviewed['deadline']+=value.deadline.value==sample['deadline']
            reviewed['key']+=any(c.text==sample['key'] for c in value.key_items)
            reviewed['mandatory_n']+=sample['mandatory']
            reviewed['mandatory_recalled']+=sample['mandatory'] and route(item,value,'ok',Profile())=='immediate'
    n=len(samples)
    return {'simulation':True,'engine':'mock/local-rules','n':n,'provenance':data['provenance'],
            'category_accuracy':counts['category']/n,'deadline_exact_accuracy_including_unknown':counts['deadline']/n,
            'deadline_precision':counts['deadline_true_positive']/max(1,counts['predicted_deadlines']),
            'deadline_recall':counts['deadline_true_positive']/max(1,counts['known_deadlines']),
            'key_item_exact_recall':counts['key']/n,'mandatory_recall':counts['mandatory_recalled']/max(1,counts['mandatory_total']),
            'mandatory_n':counts['mandatory_total'],'false_high_priority':counts['false_important'],
            'human_reviewed_subset':dict(reviewed), 'human_review_method':data.get('human_review',{}).get('method'),
            'splits':per_split,'confusion':[{'expected':a,'predicted':b,'count':v} for (a,b),v in sorted(confusion.items())],
            'errors':errors,'limitations':['开发助手编写初始样本和标签；用户确认7条，不是24条独立盲标；不代表真实LLM准确率。',
                '仅24个短文本，缺少长文、院系隐含条件、复杂日期、否定与跨句指代。',
                '日期仅提取到天，保留原文时刻证据；相对日期、多截止日期保守输出未知。',
                '关键词保护可能误将讨论考试的非强制帖子列为高优先级；未验证真实API或用户画像。']}


if __name__=='__main__':
    print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
