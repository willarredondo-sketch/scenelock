# Reference workflow

`i2v_seedance_v1.json` is the older single-image image-to-video graph (one still in, a clip out). SceneLock v0.1 does not run it.

The pipeline uses an edited end frame plus `workflows/flf_video.json` so the table, props, and light are locked by the stills before the video model runs. This file is kept so the node inputs from that earlier graph are visible.
