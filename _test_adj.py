import sys
sys.path.insert(0, '.')
from src.generators.traversing_generator import generate_traversing_workbook
from src.models.common import TraverseGrade, InstrumentGrade, AngleDefinition, AngleObservationMethod
from src.adjustment.traversing_adjustment import adjust_traverse
import math

points = [("A", 1000.0, 1000.0), ("B", 1100.0, 1050.0), ("C", 1200.0, 1080.0), ("D", 1150.0, 1150.0), ("E", 1050.0, 1130.0)]
start_az = math.atan2(50.0, 100.0)

wb = generate_traversing_workbook(
    points=points, start_azimuth=start_az, end_azimuth=start_az,
    grade=TraverseGrade.GRADE_2, instrument_grade=InstrumentGrade.SEC_2,
    angle_definition=AngleDefinition.LEFT_ANGLE,
    angle_observation_method=AngleObservationMethod.DIRECTION,
    seed=42, target_closure_ratio=0.0,
)

comp = wb.computation
print(f"azimuth_closure_error_arcsec = {comp.azimuth_closure_error_arcsec}")
print(f"fx = {comp.fx_m}")
print(f"fy = {comp.fy_m}")
print(f"fd = {comp.fd_m}")

# Run adjustment
adjust_traverse(comp)

for er in comp.edge_records:
    if er.observed_angle_rad is not None:
        corr_arcsec = er.angle_correction_rad * 206264.8 if er.angle_correction_rad else None
        print(f"{er.point_name}: v_beta = {corr_arcsec:.2f} arcsec")

# Show corrected coordinates
for pr in comp.point_records:
    print(f"  {pr.point_name}: x={pr.corrected_x_m}, y={pr.corrected_y_m}")
