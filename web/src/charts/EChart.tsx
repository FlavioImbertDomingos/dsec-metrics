/**
 * ECharts through echarts-for-react, with only the chart types we use registered.
 *
 * Canvas rendering and canvas-drawn tooltips keep ECharts from writing inline style
 * attributes, which the Content Security Policy does not allow.
 */
import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useEffect, useState } from "react";

echarts.use([
  BarChart,
  LineChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

/** Okabe-Ito, a palette that stays distinct for common colour-vision deficiencies. */
export const SERIES = {
  light: ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"],
  dark: ["#56B4E9", "#E69F00", "#2EC4A0", "#E08FC0", "#F0A860", "#8AC6F0"],
};

export const STATUS_COLORS = {
  light: { green: "#1a7f37", amber: "#9a6700", red: "#cf222e", unknown: "#6e7781" },
  dark: { green: "#3fb950", amber: "#d29922", red: "#f85149", unknown: "#8b949e" },
};

export interface ChartTheme {
  dark: boolean;
  text: string;
  muted: string;
  grid: string;
  series: string[];
  status: (typeof STATUS_COLORS)["light"];
}

function isDark(): boolean {
  return document.documentElement.classList.contains("dark");
}

/** Colours for the current theme; re-renders when the theme class changes. */
export function useChartTheme(): ChartTheme {
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setDark(isDark());
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      observer.disconnect();
    };
  }, []);
  return dark
    ? {
        dark,
        text: "#ececec",
        muted: "#b4b4b4",
        grid: "#3a3a3a",
        series: SERIES.dark,
        status: STATUS_COLORS.dark,
      }
    : {
        dark,
        text: "#262626",
        muted: "#5c5c5c",
        grid: "#e5e5e5",
        series: SERIES.light,
        status: STATUS_COLORS.light,
      };
}

interface EChartProps {
  option: Record<string, unknown>;
  label: string;
  height?: number;
}

/** A chart exposed to assistive technology as one image with a text label. */
export function EChart({ option, label, height = 220 }: EChartProps) {
  return (
    <div role="img" aria-label={label}>
      <ReactEChartsCore
        echarts={echarts}
        option={{ animation: false, aria: { enabled: false }, ...option }}
        notMerge
        opts={{ renderer: "canvas" }}
        style={{ height, width: "100%" }}
      />
    </div>
  );
}
