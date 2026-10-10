# Backyard burgers

A generic two-person meal you can copy. The scene file points at:

- `refs/location.png` — the place
- `refs/person_a.png` — the person who sits on the left
- `refs/person_b.png` — the person who sits on the right

Those files are not in the repo. Use reference photos of people who have consented, and keep them out of git (`refs/` is ignored).

The first character in the list is reference image 2 in the start-frame prompt. The second is reference image 3. The location is reference image 1. Seats (`left` / `right`) are separate from that order, and the end-frame prompt repeats the same seats.

```bash
python -m scenelock run --scene examples/backyard-burgers/scene.yaml --dry-run
```

Dry-run does not need the photos or an API key. A live run does.
