"""Merge verified source identities, then compatible equal-size pixel candidates."""
import json
from collections import defaultdict

from psd2ui.deduplication import deduplicate_images


def plan(images, metadata, references, protected, preferred, threshold, origins=None):
    usage = defaultdict(set)
    for ref in references:
        usage[ref['uuid']].add(ref['kind'])
    priority = {name:index for index,name in enumerate(dict.fromkeys(preferred))}
    files = sorted(metadata,key=lambda name:(priority.get(name,len(priority)),name))
    groups = defaultdict(list)
    originals={};replacements={}
    for name in files:
        meta = metadata[name];uid = meta['uuid']
        if not usage[uid]:
            continue
        # UUID is identity; every other metadata field must remain compatible.
        settings = {key:value for key,value in meta.items() if key!='uuid'}
        # GImage reads sizeGrid from the shared texture, so references to the
        # same original can share one canonical cut even after algorithm changes.
        if origins and name in origins and usage[uid]=={'GImage.src'}:
            compatible={**settings,'importer':{k:v for k,v in settings.get('importer',{}).items() if k!='sizeGrid'}}
            original_key=(origins[name],json.dumps(compatible,sort_keys=True))
            canonical=originals.setdefault(original_key,name)
            if canonical!=name and uid not in protected:
                replacements[name]=canonical
                continue
        key = (json.dumps(settings,sort_keys=True),tuple(sorted(usage[uid])))
        groups[key].append(name)
    for names in groups.values():
        if len(names)<2:
            continue
        root={'children':[{'type':'image','asset':name} for name in names]}
        matches=deduplicate_images(root,images,threshold)
        for old,new in matches.items():
            if metadata[old]['uuid'] not in protected:
                replacements[old]=new
    for old,new in list(replacements.items()):
        while new in replacements:new=replacements[new]
        replacements[old]=new
    return replacements
