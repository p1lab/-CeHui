import sys, dataclasses
sys.path.insert(0, '.')
from src.models.traversing import TraversePointRecord, TraverseComputation

print('=== TraversePointRecord ===')
for f in dataclasses.fields(TraversePointRecord):
    d = f.default if f.default is not dataclasses.MISSING else (f.default_factory if f.default_factory is not dataclasses.MISSING else 'REQ')
    print(f'  {f.name}: {f.type} = {d}')

print()
print('=== TraverseComputation ===')
for f in dataclasses.fields(TraverseComputation):
    d = f.default if f.default is not dataclasses.MISSING else (f.default_factory if f.default_factory is not dataclasses.MISSING else 'REQ')
    print(f'  {f.name}: {f.type} = {d}')
