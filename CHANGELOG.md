# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### 🚀 Coming Soon
- Overlay subtitles (real-time captions on meeting screen)
- Automatic meeting summary generation
- Chrome extension integration
- GPU support (faster-whisper CUDA)
- macOS/Windows support

## [0.2.0] - 2026-02-06

### ✨ Added
- **Local Whisper Integration**: faster-whisper support for offline transcription
  - `WHISPER_MODE=local` in .env
  - Multiple model sizes (tiny/base/small/medium)
  - Japanese language optimization
- **Hacker-like UI Redesign**: Complete UI overhaul
  - Dark theme with minimal gradients
  - Transparent background (frameless window)
  - Chat-style bubbles for transcripts (Speaker/Mic color-coded)
  - Monospace font (SF Mono, Monaco, Consolas)
  - Custom scrollbar
- **Always-visible Stop Button**: Floating stop button in status bar during recording
  - Auto-show when recording starts
  - Auto-hide when stopped
  - Accessible even when control panel is collapsed
- **Transcription Service Abstraction**: Unified API/Local Whisper interface
  - `transcription.py` - Single entry point for both modes
  - Automatic fallback on initialization failure
  - Debug logging for troubleshooting

### 🔄 Changed
- **Renamed**: `transcribe_mode` → `transcribe_enabled` (more appropriate for boolean)
- **Default Transcription**: Now ON by default (checkbox checked)
- **Controls Auto-collapse**: Control panel collapses when recording starts
- **DevTools**: Hidden by default (can be enabled in development)
- **Toolbar**: Removed (frameless window for cleaner look)

### 🐛 Fixed
- Field name mismatch between frontend and backend (`transcribe` vs `transcribe_mode`)
- Python venv detection in Electron main process
- System library compatibility issues (nix Python vs system glibc)

### 📚 Documentation
- **ROADMAP.md**: Comprehensive feature roadmap (short/mid/long-term)
- **BLOG_POST.md**: Project introduction blog post
- **README.md**: Complete rewrite with quick start guide, architecture diagram
- **TRANSCRIPTION_GUIDE.md**: Local/API Whisper usage guide

## [0.1.0] - 2026-02-05

### ✨ Initial Release
- **Audio Interceptor**: System-level audio capture via PulseAudio/PipeWire
- **Real-time Transcription**: OpenAI Whisper API integration
- **Meeting Detection**: Auto-detect Zoom/Google Meet
- **AI Advice**: LLM pipeline for context-aware suggestions
- **Google Calendar Integration**: Auto-populate meeting titles
- **Meeting History**: SQLite-based storage with full-text search
- **Electron Desktop App**: Cross-platform GUI (Linux tested)
- **FastAPI Backend**: WebSocket for real-time communication

---

## Version Format

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR**: Incompatible API changes
- **MINOR**: New features (backward-compatible)
- **PATCH**: Bug fixes (backward-compatible)

## Categories

- **✨ Added**: New features
- **🔄 Changed**: Changes to existing functionality
- **🗑️ Deprecated**: Soon-to-be removed features
- **🐛 Fixed**: Bug fixes
- **🔒 Security**: Vulnerability fixes
- **📚 Documentation**: Documentation changes
