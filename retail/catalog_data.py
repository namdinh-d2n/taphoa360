"""Offline category tree and source metadata, shared by public and staff screens."""
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR=Path(__file__).resolve().parents[1]/'data'


@lru_cache(maxsize=1)
def taxonomy():
    return json.loads((DATA_DIR/'categories.json').read_text(encoding='utf-8'))


def category_groups(existing=()):
    groups=[{'name':g['name'],'categories':list(g['categories'])} for g in taxonomy()]
    known={c for g in groups for c in g['categories']}
    extras=sorted(set(existing)-known)
    if extras:groups.append({'name':'Danh mục khác của tiệm','categories':extras})
    return groups


def group_for(category):
    return next((g['name'] for g in taxonomy() if category in g['categories']),'Danh mục khác của tiệm')
