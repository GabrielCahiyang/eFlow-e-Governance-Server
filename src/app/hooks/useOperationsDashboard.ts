import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchOperationsSnapshot,
  fetchTunnelSnapshot,
  rotateTunnel,
  type OperationsSnapshot,
  type TunnelSnapshot,
} from '../services/operationsService';

export function useOperationsDashboard(online: boolean) {
  const [operations, setOperations] = useState<OperationsSnapshot | null>(null);
  const [tunnel, setTunnel] = useState<TunnelSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);
  const previousEndpoint = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!online) return;
    const [operationsResult, tunnelResult] = await Promise.allSettled([
      fetchOperationsSnapshot(),
      fetchTunnelSnapshot(),
    ]);
    if (operationsResult.status === 'fulfilled') setOperations(operationsResult.value);
    if (tunnelResult.status === 'fulfilled') {
      setTunnel(tunnelResult.value);
      if (
        rotating &&
        tunnelResult.value.status === 'online' &&
        tunnelResult.value.endpoint &&
        tunnelResult.value.endpoint !== previousEndpoint.current
      ) {
        setRotating(false);
      }
    }
    const failure = [operationsResult, tunnelResult].find(
      (result): result is PromiseRejectedResult => result.status === 'rejected',
    );
    setError(failure ? String(failure.reason) : null);
  }, [online, rotating]);

  useEffect(() => {
    if (!online) {
      setError('The private AI service is offline.');
      return;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4_000);
    return () => window.clearInterval(timer);
  }, [online, refresh]);

  const requestRotation = useCallback(async () => {
    previousEndpoint.current = tunnel?.endpoint ?? null;
    setRotating(true);
    setError(null);
    try {
      await rotateTunnel();
      setTunnel((current) => current ? { ...current, rotation_pending: true } : current);
    } catch (rotationError) {
      setRotating(false);
      setError(rotationError instanceof Error ? rotationError.message : String(rotationError));
      throw rotationError;
    }
  }, [tunnel?.endpoint]);

  return {
    operations,
    tunnel,
    error,
    rotating: rotating || Boolean(tunnel?.rotation_pending),
    refresh,
    requestRotation,
  };
}
