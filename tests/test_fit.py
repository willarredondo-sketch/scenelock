from PIL import Image

from scenelock.fit import fit_character_refs
from scenelock.scene import Character, Scene


def test_fit_keeps_the_top_of_a_tall_portrait(tmp_path):
    location = Image.new("RGB", (200, 100), (8, 8, 8))
    portrait = Image.new("RGB", (40, 200), (0, 0, 255))
    top = portrait.load()
    for y in range(8):
        for x in range(40):
            top[x, y] = (255, 0, 0)
    location_path = tmp_path / "location.png"
    portrait_path = tmp_path / "person_a.png"
    other_path = tmp_path / "person_b.png"
    location.save(location_path)
    portrait.save(portrait_path)
    portrait.save(other_path)

    scene = Scene(
        title="Fit",
        setting="a table",
        location_image=location_path,
        characters=[
            Character("Person A", portrait_path, "left", "a burger", "left", "the man"),
            Character("Person B", other_path, "right", "a burger", "left", "the woman"),
        ],
        table_lock=["exactly one small ketchup cup"],
        start_pose="sitting",
        end_pose="reaching",
        motion_beat="slow",
        duration=8,
        aspect_ratio="9:16",
        image_resolution="1K",
        video_resolution="720p",
        image_model="gemini-3-pro-image-preview",
        video_model="seedance-1-5-pro-251215",
        table_bbox=None,
        seeds={"start": [], "end": [], "video": []},
    )
    fitted = fit_character_refs(scene, tmp_path / "fitted")
    image = Image.open(fitted.characters[0].image)
    assert image.size == (200, 100)
    colors = {color for _count, color in image.getcolors(maxcolors=50000)}
    assert (255, 0, 0) in colors
    # A centre crop of the tall portrait's middle misses the red band at the top.
    middle = portrait.crop((0, 90, 40, 110))
    middle_colors = {color for _count, color in middle.getcolors(maxcolors=500)}
    assert (255, 0, 0) not in middle_colors
