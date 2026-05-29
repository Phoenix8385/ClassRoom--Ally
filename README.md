# Classroom Ally — AI-Based Real-Time Speech-to-Sign Language System

Classroom Ally is a real-time AI-powered accessibility platform designed to help deaf and hard-of-hearing students understand live classroom lectures through automatic speech-to-sign language translation.

The system captures classroom speech using a laptop or mobile microphone, converts speech into text using Whisper ASR, transforms English sentences into Indian Sign Language (ISL) gloss grammar, and displays sign output through animated avatars and sign mappings in real time.

## Key Features

* Real-time speech recognition using Whisper ASR
* English-to-ISL gloss conversion engine
* WebSocket-based low-latency streaming architecture
* Real-time caption generation
* Sign language avatar rendering using Three.js / Unity
* Fingerspelling fallback for unknown words
* Human-in-the-loop feedback correction system
* Modular AI pipeline for future Conformer integration
* GPU acceleration support using NVIDIA CUDA
* Fully deployable cloud-ready architecture

## Tech Stack

### Frontend

* Next.js 15
* React 19
* Tailwind CSS
* Zustand
* Three.js / React Three Fiber

### Backend

* FastAPI
* Python 3.11
* WebSockets
* AsyncIO
* SQLAlchemy

### AI / ML

* Whisper ASR
* spaCy NLP
* MediaPipe
* PyTorch
* Silero VAD

### Database & Deployment

* PostgreSQL
* Redis
* Docker
* Vercel
* Render
* RunPod

## System Architecture

```text
Teacher Speech
      ↓
Microphone Capture
      ↓
Whisper Speech Recognition
      ↓
English Transcript
      ↓
ISL Gloss Conversion
      ↓
Sign Mapping Engine
      ↓
Avatar / Sign Rendering
      ↓
Real-Time Classroom Accessibility
```

## Project Goals

* Improve classroom accessibility for deaf students
* Reduce communication barriers in education
* Build a scalable real-time assistive AI platform
* Demonstrate practical AI system engineering
* Create a deployable and production-oriented architecture

## Engineering Highlights

* Real-time streaming pipeline
* Low-latency AI inference
* Modular microservice-style architecture
* GPU-accelerated speech processing
* Human feedback correction loop
* Resume-grade full-stack AI engineering project

## Future Improvements

* Conformer-based streaming ASR
* Emotion-aware signing
* Multi-language support
* Personalized signing styles
* Edge-device optimization
* Multi-classroom scalability

## Team

Department of Artificial Intelligence & Machine Learning
DSATM Bengaluru — 2025-26

## License

MIT License
