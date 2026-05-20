import { useState } from "react";

type EpisodeItem = {
  id: string;
  summary: string;
};

type ForgetThisProps = {
  episodes: EpisodeItem[];
  onForgetEpisode: (episodeId: string) => Promise<void>;
};

export function ForgetThis({ episodes, onForgetEpisode }: ForgetThisProps) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  return (
    <section className="forget-this">
      <h3>Forget This</h3>
      <ul>
        {episodes.map((episode) => (
          <li key={episode.id}>
            <strong>{episode.summary}</strong>
            <div>
              <button
                type="button"
                disabled={pendingId === episode.id}
                onClick={() => setConfirmId(episode.id)}
              >
                Delete This Conversation
              </button>
            </div>
            {confirmId === episode.id && (
              <div>
                <p>Episode deleted. Forget permanently?</p>
                <button
                  type="button"
                  disabled={pendingId === episode.id}
                  onClick={async () => {
                    setPendingId(episode.id);
                    try {
                      await onForgetEpisode(episode.id);
                    } finally {
                      setPendingId(null);
                      setConfirmId(null);
                    }
                  }}
                >
                  Yes
                </button>
                <button
                  type="button"
                  disabled={pendingId === episode.id}
                  onClick={() => setConfirmId(null)}
                >
                  Cancel
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
