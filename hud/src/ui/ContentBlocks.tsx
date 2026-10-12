import type { ContentBlock } from "./content";
import "./ContentBlocks.css";
import { openLink } from "./panelChannel";

/** Renders one typed block. Unknown kinds are dropped rather than thrown on, so a
 *  newer backend cannot take the HUD down with a block this build has not learned. */
function Block({ block }: { block: ContentBlock }) {
  switch (block.kind) {
    case "heading":
      return block.level === 3 ? (
        <h3 className="cb-h3">{block.text}</h3>
      ) : (
        <h2 className="cb-h2">
          <span className="cb-h2-rule" aria-hidden="true" />
          {block.text}
        </h2>
      );

    case "text":
      return <p className="cb-text">{block.text}</p>;

    case "quote":
      return (
        <blockquote className="cb-quote">
          <p>{block.text}</p>
          {block.attribution ? <cite className="readout">{block.attribution}</cite> : null}
        </blockquote>
      );

    case "image":
      return (
        <figure className="cb-figure">
          <div className="cb-figure-frame">
            <img src={block.src} alt={block.alt} />
          </div>
          {block.caption ? (
            <figcaption className="cb-caption readout">{block.caption}</figcaption>
          ) : null}
        </figure>
      );

    case "sourceList":
      return (
        <section className="cb-sources">
          <div className="cb-sources-label readout">{block.label ?? "SOURCES"}</div>
          <ol>
            {block.sources.map((source) => (
              <li key={source.index}>
                <span className="cb-source-title">{source.title}</span>
                <span className="cb-source-meta readout">
                  {source.publisher} &middot; {source.year}
                </span>
              </li>
            ))}
          </ol>
        </section>
      );

    case "link":
      return (
        <button type="button" className="cb-link" onClick={() => openLink(block.url)} title={block.url}>
          <span className="cb-link-text">{block.text}</span>
          {block.note ? <span className="cb-link-note readout">{block.note}</span> : null}
        </button>
      );

    case "screenshot": {
      const url = block.url;
      return (
        <figure
          className={url ? "cb-figure cb-shot is-link" : "cb-figure cb-shot"}
          onClick={url ? () => openLink(url) : undefined}
        >
          <div className="cb-figure-frame">
            <img src={block.src} alt={block.caption ?? "screenshot"} />
          </div>
          {block.caption ? <figcaption className="cb-caption readout">{block.caption}</figcaption> : null}
        </figure>
      );
    }

    case "video":
      return (
        <button type="button" className="cb-video" onClick={() => openLink(block.url)} title={block.url}>
          {block.thumbnail ? <img className="cb-video-thumb" src={block.thumbnail} alt="" /> : <span className="cb-video-thumb" />}
          <span className="cb-video-meta">
            <span className="cb-video-title">{block.title}</span>
            <span className="cb-video-sub readout">
              {block.channel} &middot; {block.duration}
            </span>
          </span>
        </button>
      );

    case "weather": {
      const url = block.url;
      return (
        <section className={url ? "cb-weather is-link" : "cb-weather"} onClick={url ? () => openLink(url) : undefined}>
          <div className="cb-weather-now">
            <span className="cb-weather-temp">{block.temp !== undefined ? `${block.temp}°` : "—"}</span>
            <span className="cb-weather-sky">
              {block.sky}
              <span className="readout">
                {block.low !== undefined && block.high !== undefined ? `${block.low}–${block.high}°C` : ""}
                {block.rain !== undefined ? ` · rain ${block.rain}%` : ""}
                {block.streak && block.streak >= 2 ? ` · day ${block.streak} of rain` : ""}
              </span>
            </span>
          </div>
          {block.days?.length ? (
            <ol className="cb-weather-days">
              {block.days.map((d) => (
                <li key={d.day}>
                  <b>{d.day}</b>
                  <span>{d.sky}</span>
                  <span className="readout">
                    {d.low}–{d.high}° · {d.rain}%
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      );
    }

    case "price": {
      const url = block.url;
      const dir = block.up === true ? "is-up" : block.up === false ? "is-down" : "is-flat";
      return (
        <button type="button" className={`cb-price ${dir}`} onClick={url ? () => openLink(url) : undefined} title={url}>
          <span className="cb-price-label">
            {block.label}
            {block.note ? <span className="readout">{block.note}</span> : null}
          </span>
          {block.spark && block.spark.length > 1 ? <Spark values={block.spark} /> : <span className="cb-spark" />}
          <span className="cb-price-value">
            {block.value}
            <span className="cb-price-change">
              {block.up === true ? "▲ " : block.up === false ? "▼ " : ""}
              {block.change}
            </span>
          </span>
        </button>
      );
    }

    case "story":
      return (
        <button type="button" className="cb-story" onClick={() => openLink(block.url)} title={block.url}>
          {block.image ? <img className="cb-story-thumb" src={block.image} alt="" /> : <span className="cb-story-thumb" />}
          <span className="cb-story-meta">
            <span className="cb-story-title">{block.title}</span>
            {block.original ? <span className="cb-story-original">{block.original}</span> : null}
            <span className="cb-story-sub readout">
              {block.source}
              {block.also?.length ? ` · also ${block.also.join(", ")}` : ""}
            </span>
          </span>
        </button>
      );

    default:
      return null;
  }
}

/** A small line of recent values, its last point marked. */
function Spark({ values }: { values: number[] }) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, k) => [(k / (values.length - 1)) * 100, 28 - ((v - lo) / span) * 24]);
  const last = pts[pts.length - 1];
  return (
    <svg className="cb-spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} />
      <circle cx={last[0]} cy={last[1]} r="2.2" />
    </svg>
  );
}

export function ContentBlocks({ blocks }: { blocks: ContentBlock[] }) {
  return (
    <>
      {blocks.map((block, index) => (
        <Block key={index} block={block} />
      ))}
    </>
  );
}

export default ContentBlocks;
