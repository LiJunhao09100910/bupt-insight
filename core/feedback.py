"""Explicit version-bound local feedback. Never modifies delivery receipts."""
import json
from core.database import now
from core.errors import InsightError

LABELS = ('important','relevant','irrelevant','unsure')


def record(db, row, profile, label, note='', explanation_quality=None):
    if label not in LABELS or explanation_quality not in (None,1,2,3,4,5):
        raise InsightError('feedback_invalid','反馈标签或解释评分无效')
    with db.db:
        return db.db.execute('''INSERT INTO feedback(notice_id,content_hash,profile_hash,label,note,explanation_quality,created_at)
          VALUES(?,?,?,?,?,?,?)''',(row['id'],row['hash'],profile.fingerprint(),label,note[:500],explanation_quality,now())).lastrowid


def latest(db,row,profile):
    return db.db.execute('''SELECT label,explanation_quality FROM feedback
      WHERE notice_id=? AND content_hash=? AND profile_hash=? ORDER BY id DESC LIMIT 1''',
      (row['id'],row['hash'],profile.fingerprint())).fetchone()
