# Development & Technical Architecture

This document tracks the technical evolution, optimization strategies, and AI-assisted refinements of the ETC-Center-Table project.

## 🛠️ Data Pipeline & Extraction
The core challenge of this project is transforming unstructured mathematical strings from the Encyclopedia of Triangle Centers (ETC) into structured, evaluatable data.

* **Scraping Strategy:** Python-based extraction using `BeautifulSoup4` and `requests`. The pipeline is designed to be stateful, identifying the highest processed $X_n$ to allow for incremental updates.
* **AST Serialization:** To handle complex barycentric coordinates, we utilize Python's `ast` (Abstract Syntax Tree) module. This ensures that coordinates are parsed as mathematical structures rather than simple strings, preventing evaluation errors in the frontend.
* **Performance Optimization:** We implement `multiprocessing` to handle batch processing of thousands of centers. This is currently optimized for Windows and MyBinder environments to ensure cross-platform stability.

## 🖥️ Frontend & Visualization
* **Architecture:** The project follows a "Decoupled Data" approach. Visual logic is handled by `JSXGraph` and `GeoGebra`, while the coordinate data is served via lightweight JSON/JS files.
* **Refactoring:** The site was recently restructured from a single-page list to a multi-page "Introduction" (`intro.html`) and "Discovery Sandbox" (`discovery_sandbox.html`) to improve user onboarding and cognitive load management.

## 🤖 AI Collaboration Log
This project leverages advanced AI agents (Claude, Codex) to accelerate development in the following areas:
* Refining complex Regex patterns for coordinate filtering.
* Optimizing multiprocessing worker pools to prevent memory leaks during large batch runs.
* Refactoring CSS for high-fidelity geometric rendering and responsive UI layouts.
