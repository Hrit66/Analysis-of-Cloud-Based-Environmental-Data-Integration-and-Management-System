import { useEffect, useMemo, useState } from 'react';
import { fetchDatasets } from '../lib/api';

/**
 * Pick the dataset a dashboard should show: only datasets that actually
 * contain the requested capability, never a fallback to another kind.
 * Returns `selectedId: null` when nothing compatible exists so pages can
 * render an explicit empty state.
 */
export function useDatasetFor(capability) {
  const [datasets, setDatasets] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    fetchDatasets()
      .then(all => {
        if (!active) return;
        const matches = (Array.isArray(all) ? all : [])
          .filter(d => d.status === 'completed' && (d.capabilities || []).includes(capability))
          .sort((a, b) => {
            const byCreated = new Date(b.created_at || 0) - new Date(a.created_at || 0);
            if (byCreated !== 0) return byCreated;
            return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
          });
        setDatasets(matches);
        setSelectedId(prev => (matches.some(match => match.id === prev) ? prev : (matches[0]?.id ?? null)));
      })
      .catch(err => {
        if (active) setError(err.message || 'Failed to load datasets');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => { active = false; };
  }, [capability]);

  const selected = useMemo(
    () => datasets.find(dataset => dataset.id === selectedId) || null,
    [datasets, selectedId]
  );

  return { datasets, selectedId, setSelectedId, selected, loading, error };
}
