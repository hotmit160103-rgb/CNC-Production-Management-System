import json

from transformation import DigitalTwinTransformer


with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

config["active_machine_id"] = "EMCO_155"

with open("input_post1.nc", "r", encoding="utf-8", errors="ignore") as f:
    nc_program_text = f.read()

transformer = DigitalTwinTransformer(config)
geometry_chain = transformer.build_geometry_chain(nc_program_text)

print("Total MotionBlocks:", len(geometry_chain))

for block in geometry_chain[:10]:
    print(
        block.line_number,
        block.motion_type,
        block.geometry_source,
        round(block.path_length_mm, 4),
        block.commanded_feed_mm_min,
        block.start_position_mcs,
        "->",
        block.end_position_mcs,
    )
