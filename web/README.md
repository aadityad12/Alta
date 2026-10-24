# web

Student screen (React + Vite + TypeScript). Run it with `scripts/dev.sh` from the repo root, or `npm run dev` here (server must be on :8000).

The dev server proxies `/ws`, `/labs` and `/health` to `http://localhost:8000`.

- `npm test`: unit tests (vitest)
- <http://localhost:5173/dev/board>: overlay engine playground on the sample photos/video, or a webcam (#11, see `src/board/README.md`)
