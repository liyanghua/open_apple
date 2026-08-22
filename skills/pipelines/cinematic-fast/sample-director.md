# Sample Director - Cinematic Fastline

There is no same-named base director. Before acting, read the complete
`skills/pipelines/cinematic/asset-director.md`,
`skills/pipelines/cinematic/compose-director.md` and
`skills/meta/fastline.md`. After the creative bundle is approved, materialize
or generate approved TTS/BGM/subtitle/proxy assets, compile `final_props` and
`render_plan`, render a 10-15 second sample through `video_compose`, and run
quick `final_qa`. Also build `sample_execution_trace` from the approved
`shot_execution_plan` and realized `final_props`, showing which locked shots
are included, partial, new, or outside the sample window. Pause for sample
approval; approval covers both the sample video and this execution trace. Do
not advance to edit or final compose before that approval. The operator must
also complete the five effect checks: creative direction, hook, proof clarity,
pacing/cuts, and caption/visual readability. Only five ``pass`` decisions may
advance the pipeline; ``adjust`` routes to edit and ``redirect`` reopens the
creative direction gate.
