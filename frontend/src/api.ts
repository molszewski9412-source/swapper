import { io, Socket } from 'socket.io-client';
import type { Status } from './types';

const API_BASE = 'http://localhost:12000';

let socket: Socket | null = null;

export const connectWebSocket = (onUpdate: (status: Status) => void): Socket => {
  if (socket?.connected) {
    return socket;
  }

  socket = io(API_BASE, {
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 1000,
  });

  socket.on('connect', () => {
    console.log('WebSocket connected');
    socket?.emit('request_status');
  });

  socket.on('status_update', (status: Status) => {
    onUpdate(status);
  });

  socket.on('swap_executed', (data: any) => {
    console.log('Swap executed:', data);
    socket?.emit('request_status');
  });

  socket.on('disconnect', () => {
    console.log('WebSocket disconnected');
  });

  return socket;
};

export const disconnectWebSocket = () => {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
};

export const requestStatus = () => {
  socket?.emit('request_status');
};

export const fetchStatus = async (): Promise<Status> => {
  const res = await fetch(`${API_BASE}/api/status`);
  return res.json();
};

export const startTrader = async (): Promise<{ status: string }> => {
  const res = await fetch(`${API_BASE}/api/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'start' }),
  });
  return res.json();
};

export const stopTrader = async (): Promise<{ status: string }> => {
  const res = await fetch(`${API_BASE}/api/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'stop' }),
  });
  return res.json();
};

export const resetTrader = async (): Promise<{ status: string }> => {
  const res = await fetch(`${API_BASE}/api/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'reset' }),
  });
  return res.json();
};
