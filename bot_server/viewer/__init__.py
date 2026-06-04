"""Optional graphic-recording viewer mounted at /v/{slug}.

Only loaded when ``settings.viewer_enabled`` is True. The canvas pipeline
(chunker → LLM → IR → SVG) is lifted from `/home/tan_t/workspace/canvas`
(same author); see `bot_server/viewer/canvas/` for the lifted modules.
"""
