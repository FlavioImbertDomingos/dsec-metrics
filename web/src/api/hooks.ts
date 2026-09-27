/** TanStack Query hooks for the read API. Keys include every parameter. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  BatchPage,
  ControlDetail,
  ControlSummary,
  Dashboard,
  DashboardSummary,
  ExceptionItem,
  FindingItem,
  MeasurementDetail,
  MetricDetail,
  MetricHistory,
  MetricSummary,
  Register,
} from "@/api/types";
import { withQuery } from "@/lib/router";

type Params = Record<string, string | undefined>;

function get<T>(path: string, params: Params = {}) {
  return api<T>(withQuery(path, params));
}

const STALE = 30_000;

export function useDashboards() {
  return useQuery({
    queryKey: ["dashboards"],
    queryFn: () => get<DashboardSummary[]>("/api/dashboards"),
    staleTime: STALE,
  });
}

export function useDashboard(id: string, filters: Params) {
  return useQuery({
    queryKey: ["dashboard", id, filters],
    queryFn: () => get<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}`, filters),
    staleTime: STALE,
    placeholderData: keepPreviousData,
  });
}

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => get<MetricSummary[]>("/api/metrics"),
    staleTime: STALE,
  });
}

export function useMetric(id: string) {
  return useQuery({
    queryKey: ["metric", id],
    queryFn: () => get<MetricDetail>(`/api/metrics/${encodeURIComponent(id)}`),
    staleTime: STALE,
  });
}

export function useMetricHistory(id: string, filters: Params) {
  return useQuery({
    queryKey: ["metric-history", id, filters],
    queryFn: () =>
      get<MetricHistory>(`/api/metrics/${encodeURIComponent(id)}/measurements`, filters),
    staleTime: STALE,
    placeholderData: keepPreviousData,
  });
}

export function useMeasurement(id: string) {
  return useQuery({
    queryKey: ["measurement", id],
    queryFn: () => get<MeasurementDetail>(`/api/measurements/${encodeURIComponent(id)}`),
    staleTime: Infinity, // measurements never change
  });
}

export function useBatch(sha256: string, offset: number, limit: number) {
  return useQuery({
    queryKey: ["batch", sha256, offset, limit],
    queryFn: () =>
      get<BatchPage>(`/api/batches/${encodeURIComponent(sha256)}`, {
        offset: String(offset),
        limit: String(limit),
      }),
    staleTime: Infinity, // batches never change
    placeholderData: keepPreviousData,
  });
}

export function useControls() {
  return useQuery({
    queryKey: ["controls"],
    queryFn: () => get<ControlSummary[]>("/api/controls"),
    staleTime: STALE,
  });
}

export function useControl(id: string) {
  return useQuery({
    queryKey: ["control", id],
    queryFn: () => get<ControlDetail>(`/api/controls/${encodeURIComponent(id)}`),
    staleTime: STALE,
  });
}

export function useExceptions(filters: Params) {
  return useQuery({
    queryKey: ["exceptions", filters],
    queryFn: () => get<Register<ExceptionItem>>("/api/exceptions", filters),
    staleTime: STALE,
    placeholderData: keepPreviousData,
  });
}

export function useFindings(filters: Params) {
  return useQuery({
    queryKey: ["findings", filters],
    queryFn: () => get<Register<FindingItem>>("/api/findings", filters),
    staleTime: STALE,
  });
}
