/** jsdom has no canvas; tests render the chart's option as data instead. */
export default function ReactEChartsCore({ option }: { option: { series?: unknown[] } }) {
  return <div data-testid="echart" data-series={String(option.series?.length ?? 0)} />;
}
