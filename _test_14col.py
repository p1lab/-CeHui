import sys
sys.path.insert(0, '.')
from src.generators.traversing_generator import generate_traversing_workbook
from src.formatters.text_formatter import workbook_to_text
from src.models.common import TraverseGrade, InstrumentGrade, AngleDefinition, AngleObservationMethod
import math

# 闭合导线 5 点 (more data)
points = [
    ("A", 1000.0, 1000.0),
    ("B", 1100.0, 1050.0),
    ("C", 1200.0, 1080.0),
    ("D", 1150.0, 1150.0),
    ("E", 1050.0, 1130.0),
]
start_az = math.atan2(50.0, 100.0)

wb = generate_traversing_workbook(
    points=points, start_azimuth=start_az, end_azimuth=start_az,
    grade=TraverseGrade.GRADE_2, instrument_grade=InstrumentGrade.SEC_2,
    angle_definition=AngleDefinition.LEFT_ANGLE,
    angle_observation_method=AngleObservationMethod.DIRECTION,
    seed=42, target_closure_ratio=0.3,
)

text = workbook_to_text(wb)
lines = text.split('\n')
in_comp = False
count = 0
for line in lines:
    if '成果计算' in line:
        in_comp = True
    if in_comp:
        print(line)
        count += 1
    if in_comp and '闭合差' in line:
        # print a few more lines
        break

# Also print the rest after closure
for line in lines[lines.index([l for l in lines if '闭合差' in l][0]):]:
    if '闭合差' in line or count > 0:
        print(line)
        count += 1
    if count > 30:
        break
