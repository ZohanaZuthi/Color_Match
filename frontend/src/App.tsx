import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
  type KeyboardEvent,
} from "react";
import {
  Crop,
  Hand,
  ImagePlus,
  LoaderCircle,
  Minus,
  Plus,
  RotateCcw,
} from "lucide-react";
import { api, type Region, type StudyImage } from "./api";

type Result = {
  percentages: {
    red: number;
    yellow: number;
    blue: number;
    white: number;
  } | null;
  hex: string;
  message: string | null;
};
type Point = { x: number; y: number };
const clamp = (n: number, low = 0, high = 1) =>
  Math.min(high, Math.max(low, n));

export default function App() {
  const [photo, setPhoto] = useState<StudyImage | null>(null);
  const [zoom, setZoom] = useState(1);
  const [mode, setMode] = useState<"select" | "move">("select");
  const [region, setRegion] = useState<Region | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [viewSize, setViewSize] = useState({ width: 800, height: 500 });
  const fileInput = useRef<HTMLInputElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const start = useRef<Point | null>(null);
  const pan = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const anchor = useRef<Point | null>(null);
  const pending = useRef<AbortController | null>(null);
  const uploadLock = useRef(false);

  useEffect(() => {
    const element = viewport.current!;
    const observer = new ResizeObserver(() =>
      setViewSize({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      pending.current?.abort();
    };
  }, []);

  const fit = photo
    ? Math.min(
        (viewSize.width - 32) / photo.width,
        (viewSize.height - 32) / photo.height,
      )
    : 1;
  const width = photo ? photo.width * fit * zoom : 0;
  const height = photo ? photo.height * fit * zoom : 0;

  useLayoutEffect(() => {
    const v = viewport.current,
      f = frame.current,
      a = anchor.current;
    if (v && f && a) {
      v.scrollLeft = f.offsetLeft + a.x * f.clientWidth - v.clientWidth / 2;
      v.scrollTop = f.offsetTop + a.y * f.clientHeight - v.clientHeight / 2;
      anchor.current = null;
    }
  }, [zoom, width, height]);

  function changeZoom(value: number) {
    const v = viewport.current,
      f = frame.current;
    if (v && f)
      anchor.current = {
        x: clamp(
          (v.scrollLeft + v.clientWidth / 2 - f.offsetLeft) / f.clientWidth,
        ),
        y: clamp(
          (v.scrollTop + v.clientHeight / 2 - f.offsetTop) / f.clientHeight,
        ),
      };
    setZoom(clamp(value, 1, 8));
  }

  async function analyze(selection: Region) {
    if (!photo || uploadLock.current) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy("Reading color");
    setError("");
    setResult(null);
    try {
      const response = await api<Result>(
        `/images/${photo.id}/primary`,
        selection,
        controller.signal,
      );
      if (!controller.signal.aborted) setResult(response);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setBusy("");
    }
  }

  async function upload(file: File) {
    if (uploadLock.current) return;
    if (file.size > 15 * 1024 * 1024) {
      setError("Please choose a photo smaller than 15 MB.");
      return;
    }
    pending.current?.abort();
    uploadLock.current = true;
    setBusy("Opening photo");
    setError("");
    setResult(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const image = await api<StudyImage>("/images", body);
      setPhoto(image);
      setZoom(1);
      setRegion(null);
      setMode("select");
      anchor.current = null;
      viewport.current?.scrollTo(0, 0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      uploadLock.current = false;
      setBusy("");
    }
  }

  function point(event: PointerEvent): Point {
    const box = frame.current!.getBoundingClientRect();
    return {
      x: clamp((event.clientX - box.left) / box.width),
      y: clamp((event.clientY - box.top) / box.height),
    };
  }
  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!photo || uploadLock.current || event.button !== 0) return;
    if (mode === "move") {
      pan.current = {
        x: event.clientX,
        y: event.clientY,
        left: event.currentTarget.scrollLeft,
        top: event.currentTarget.scrollTop,
      };
    } else {
      if (!frame.current?.contains(event.target as Node)) return;
      pending.current?.abort();
      setBusy("");
      setResult(null);
      start.current = point(event);
      setRegion({ ...start.current, width: 0, height: 0 });
    }
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function selectionTo(end: Point): Region {
    const begin = start.current!;
    return {
      x: Math.min(begin.x, end.x),
      y: Math.min(begin.y, end.y),
      width: Math.abs(begin.x - end.x),
      height: Math.abs(begin.y - end.y),
    };
  }
  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    if (pan.current) {
      event.currentTarget.scrollLeft =
        pan.current.left - (event.clientX - pan.current.x);
      event.currentTarget.scrollTop =
        pan.current.top - (event.clientY - pan.current.y);
    } else if (start.current) setRegion(selectionTo(point(event)));
  }
  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    if (pan.current) {
      pan.current = null;
      return;
    }
    if (!start.current || !photo) return;
    const end = point(event);
    let selection = selectionTo(end);
    if (selection.width * width < 3 || selection.height * height < 3) {
      const w = Math.min(1, 5 / photo.width),
        h = Math.min(1, 5 / photo.height);
      selection = {
        x: clamp(end.x - w / 2, 0, 1 - w),
        y: clamp(end.y - h / 2, 0, 1 - h),
        width: w,
        height: h,
      };
    }
    start.current = null;
    setRegion(selection);
    void analyze(selection);
  }

  function keyboardSelection(event: KeyboardEvent<HTMLDivElement>) {
    if (!photo || uploadLock.current) return;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      changeZoom(zoom + 0.5);
      return;
    }
    if (event.key === "-") {
      event.preventDefault();
      changeZoom(zoom - 0.5);
      return;
    }
    const r = region || { x: 0.45, y: 0.45, width: 0.1, height: 0.1 };
    const next = { ...r };
    const step = 0.01;
    switch (event.key) {
      case "ArrowLeft":
        event.shiftKey
          ? (next.width = clamp(r.width - step, 1 / photo.width, 1 - r.x))
          : (next.x = clamp(r.x - step, 0, 1 - r.width));
        break;
      case "ArrowRight":
        event.shiftKey
          ? (next.width = clamp(r.width + step, 1 / photo.width, 1 - r.x))
          : (next.x = clamp(r.x + step, 0, 1 - r.width));
        break;
      case "ArrowUp":
        event.shiftKey
          ? (next.height = clamp(r.height - step, 1 / photo.height, 1 - r.y))
          : (next.y = clamp(r.y - step, 0, 1 - r.height));
        break;
      case "ArrowDown":
        event.shiftKey
          ? (next.height = clamp(r.height + step, 1 / photo.height, 1 - r.y))
          : (next.y = clamp(r.y + step, 0, 1 - r.height));
        break;
      case "Enter":
        event.preventDefault();
        setRegion(r);
        void analyze(r);
        return;
      default:
        return;
    }
    event.preventDefault();
    pending.current?.abort();
    setBusy("");
    setResult(null);
    setRegion(next);
  }

  return (
    <main className="app">
      <header>
        <a className="brand" href="/" aria-label="Watercolor home">
          <span className="brand-dots">
            <i />
            <i />
            <i />
          </span>
          Watercolor
        </a>
        <button
          className="upload-button"
          onClick={() => fileInput.current?.click()}
          disabled={busy === "Opening photo"}
        >
          <ImagePlus size={18} />
          {photo ? "Change photo" : "Upload photo"}
        </button>
      </header>
      <div className="introduction">
        <h1>Pick a color. Find the mix.</h1>
        <p>Upload a photo, zoom in, and select the area you want to match.</p>
      </div>
      <input
        className="file-input"
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        aria-label="Upload photo file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
          e.target.value = "";
        }}
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <section className="photo-panel" aria-label="Photo and area selection">
        <div className="toolbar">
          <div className="modes">
            <button
              title="Drag to select an area"
              aria-pressed={mode === "select"}
              disabled={!photo}
              onClick={() => setMode("select")}
            >
              <Crop size={17} />
              Select
            </button>
            <button
              title="Drag to move the zoomed photo"
              aria-pressed={mode === "move"}
              disabled={!photo}
              onClick={() => setMode("move")}
            >
              <Hand size={17} />
              Move
            </button>
          </div>
          <div className="zoom">
            <button
              aria-label="Zoom out"
              disabled={!photo || zoom <= 1}
              onClick={() => changeZoom(zoom - 0.5)}
            >
              <Minus size={18} />
            </button>
            <input
              aria-label="Zoom level"
              type="range"
              min="1"
              max="8"
              step="0.1"
              value={zoom}
              disabled={!photo}
              onChange={(e) => changeZoom(Number(e.target.value))}
            />
            <span className="zoom-value">{Math.round(zoom * 100)}%</span>
            <button
              aria-label="Zoom in"
              disabled={!photo || zoom >= 8}
              onClick={() => changeZoom(zoom + 0.5)}
            >
              <Plus size={18} />
            </button>
            <button
              className="fit"
              aria-label="Fit photo"
              disabled={!photo}
              onClick={() => changeZoom(1)}
            >
              <RotateCcw size={16} />
              <span>Fit</span>
            </button>
          </div>
        </div>
        <div
          ref={viewport}
          className={`viewport ${mode}`}
          tabIndex={photo ? 0 : -1}
          aria-label="Photo selection. Arrow keys move the selection; Shift and arrows resize; Enter reads the color. Plus and minus zoom."
          onKeyDown={keyboardSelection}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerUp={pointerUp}
          onPointerCancel={() => {
            start.current = null;
            pan.current = null;
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (file) void upload(file);
          }}
        >
          {photo ? (
            <div
              className="image-sheet"
              style={{
                width: Math.max(viewSize.width, width + 32),
                height: Math.max(viewSize.height, height + 32),
              }}
            >
              <div
                className="photo-frame"
                ref={frame}
                style={{ width, height }}
              >
                <img
                  src={photo.url}
                  alt="Your uploaded reference"
                  draggable={false}
                />
                {region && (
                  <div
                    className="selection"
                    style={{
                      left: `${region.x * 100}%`,
                      top: `${region.y * 100}%`,
                      width: `${region.width * 100}%`,
                      height: `${region.height * 100}%`,
                    }}
                  >
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="empty">
              <div className="photo-icon">
                <ImagePlus size={38} strokeWidth={1.4} />
              </div>
              <h2>Start with a photo</h2>
              <p>Drop it here, or choose one from your device.</p>
              <button
                className="upload-button"
                onClick={() => fileInput.current?.click()}
                disabled={!!busy}
              >
                Choose photo
              </button>
              <small>JPG, PNG or WebP</small>
            </div>
          )}
        </div>
        <p className="selection-help">
          {busy ? (
            <>
              <LoaderCircle className="spin" size={15} />
              {busy}…
            </>
          ) : photo ? (
            mode === "move" ? (
              "Drag the photo to move around. Switch to Select to pick an area."
            ) : (
              "Drag a box over an area, or click to sample a single spot."
            )
          ) : (
            "Your photo will appear here."
          )}
        </p>
      </section>
      <section
        className="result"
        aria-label="Red, yellow, blue and white percentages"
        aria-live="polite"
      >
        <div className="result-heading">
          <h2>Your estimated color mix</h2>
          {result && (
            <span
              className="sample"
              style={{ background: result.hex }}
              aria-label="Selected color"
            />
          )}
        </div>
        <div className="primaries">
          {(["red", "yellow", "blue", "white"] as const).map((color) => (
            <div className={`primary-card ${color}`} key={color}>
              <span className="primary-label">
                <i />
                {color}
              </span>
              <strong>
                {result?.percentages ? `${result.percentages[color]}%` : "—"}
              </strong>
              <div className="track">
                <span
                  style={{ width: `${result?.percentages?.[color] || 0}%` }}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="result-note">
          {result?.message ||
            (result?.percentages
              ? "Approximate color proportions, not measured paint amounts."
              : "Select an area to see its red, yellow, blue and white proportions.")}
          {result?.percentages && (
            <>
              {" "}
              White estimates a light tint, not water dilution.
              {result.message && " These are not measured paint amounts."}
            </>
          )}
        </p>
      </section>
    </main>
  );
}
