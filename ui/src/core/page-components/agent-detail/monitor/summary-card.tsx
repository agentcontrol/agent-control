"use client";

import { LineChart } from "@mantine/charts";
import {
  Box,
  Card,
  Grid,
  Group,
  RingProgress,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconActivity,
  IconAlertTriangle,
  IconCheck,
  IconX,
} from "@tabler/icons-react";
import React, { useEffect, useMemo, useState } from "react";

import type { TimeseriesBucket } from "@/core/hooks/query-hooks/use-agent-monitor";

import type { SummaryMetrics } from "./types";

interface SummaryCardProps {
  summary: SummaryMetrics;
  timeseries?: TimeseriesBucket[] | null;
  timeRange: string;
}

// Format timestamp based on time range
function formatTimestamp(timestamp: string, timeRange: string): string {
  const date = new Date(timestamp);
  
  if (["1m", "5m", "15m", "1h"].includes(timeRange)) {
    return date.toLocaleTimeString([], { 
      hour: "2-digit", 
      minute: "2-digit" 
    });
  }
  
  if (timeRange === "24h") {
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  
  return date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
}

// Metric card component - uses neutral background with colored left border accent
function MetricCard({ 
  label, 
  value, 
  icon: Icon, 
  color,
  tooltip,
}: { 
  label: string; 
  value: number; 
  icon: React.ElementType;
  color: string;
  tooltip?: string;
}) {
  const content = (
    <Box
      p="md"
      style={{
        borderRadius: "var(--mantine-radius-md)",
        backgroundColor: "var(--mantine-color-default)",
        border: "1px solid var(--mantine-color-default-border)",
        borderLeft: `4px solid var(--mantine-color-${color}-6)`,
      }}
    >
      <Group gap="sm" wrap="nowrap">
        <Box
          p={8}
          style={{
            borderRadius: "var(--mantine-radius-sm)",
            backgroundColor: `var(--mantine-color-${color}-light)`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Icon 
            size={20} 
            style={{ color: `var(--mantine-color-${color}-6)` }}
          />
        </Box>
        <Stack gap={2}>
          <Text size="sm" fw={500}>
            {label}
          </Text>
          <Text size="xl" fw={700} c={`${color}.6`}>
            {value.toLocaleString()}
          </Text>
        </Stack>
      </Group>
    </Box>
  );

  if (tooltip) {
    return <Tooltip label={tooltip}>{content}</Tooltip>;
  }
  return content;
}

// Custom hook for animating a value from 0 to 1
function useAnimatedProgress(dependencies: unknown[], duration = 1000) {
  const [progress, setProgress] = useState(0);
  const animationRef = React.useRef<number | undefined>(undefined);
  const startTimeRef = React.useRef<number | undefined>(undefined);
  
  useEffect(() => {
    // Start fresh animation
    startTimeRef.current = Date.now();
    
    const animate = () => {
      const elapsed = Date.now() - (startTimeRef.current || Date.now());
      const rawProgress = Math.min(elapsed / duration, 1);
      // Ease-out cubic for smooth deceleration
      const eased = 1 - Math.pow(1 - rawProgress, 3);
      setProgress(eased);
      
      if (rawProgress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };
    
    // Start from 0 by immediately setting and then animating
    setProgress(0);
    // Use setTimeout to ensure the 0 is rendered before animating
    const timeoutId = setTimeout(() => {
      animationRef.current = requestAnimationFrame(animate);
    }, 16);
    
    return () => {
      clearTimeout(timeoutId);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  
  return progress;
}

export function SummaryCard({ summary, timeseries, timeRange }: SummaryCardProps) {
  // Animation progress for RingProgress (0 to 1)
  const ringAnimationProgress = useAnimatedProgress(
    [timeRange, summary.totalMatches],
    1000
  );

  // Transform timeseries data for Mantine charts
  const chartData = useMemo(() => {
    if (!timeseries) return [];
    return timeseries.map((bucket) => ({
      timestamp: formatTimestamp(bucket.timestamp, timeRange),
      Triggers: bucket.match_count,
      "Non-Matches": bucket.non_match_count,
      Errors: bucket.error_count,
    }));
  }, [timeseries, timeRange]);

  // Check if there's any chart data to display
  const hasChartData = timeseries && timeseries.some(
    (bucket) => 
      bucket.match_count > 0 || 
      bucket.non_match_count > 0 || 
      bucket.error_count > 0
  );

  return (
    <Card withBorder p="lg" radius="md">
      <Stack gap="lg">
        {/* Top: Metrics Row */}
        <SimpleGrid cols={4} spacing="md">
          <MetricCard
            label="Executions"
            value={summary.totalExecutions}
            icon={IconActivity}
            color="blue"
            tooltip="Total control evaluations"
          />
          <MetricCard
            label="Triggers"
            value={summary.totalMatches}
            icon={IconAlertTriangle}
            color="orange"
            tooltip="Controls that matched (triggered action)"
          />
          <MetricCard
            label="Non-Matches"
            value={summary.totalNonMatches}
            icon={IconCheck}
            color="green"
            tooltip="Controls that did not match (passed)"
          />
          <MetricCard
            label="Errors"
            value={summary.totalErrors}
            icon={IconX}
            color="red"
            tooltip="Errors during control evaluation"
          />
        </SimpleGrid>

        {/* Bottom: Chart + Actions Distribution */}
        <Grid gutter="lg">
          {/* Left: Trend Chart */}
          <Grid.Col span={8}>
            <Box
              p="md"
              style={{
                borderRadius: "var(--mantine-radius-sm)",
                backgroundColor: "var(--mantine-color-default)",
                border: "1px solid var(--mantine-color-default-border)",
                height: "100%",
              }}
            >
              <Stack gap="sm" h="100%">
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={600}>
                    Activity Trend
                  </Text>
                  {/* Compact Legend */}
                  <Group gap="md">
                    <Group gap={4}>
                      <Box
                        w={10}
                        h={10}
                        style={{
                          borderRadius: 2,
                          backgroundColor: "var(--mantine-color-orange-5)",
                        }}
                      />
                      <Text size="xs" c="dimmed">Triggers</Text>
                    </Group>
                    <Group gap={4}>
                      <Box
                        w={10}
                        h={10}
                        style={{
                          borderRadius: 2,
                          backgroundColor: "var(--mantine-color-green-5)",
                        }}
                      />
                      <Text size="xs" c="dimmed">Non-Matches</Text>
                    </Group>
                    <Group gap={4}>
                      <Box
                        w={10}
                        h={10}
                        style={{
                          borderRadius: 2,
                          backgroundColor: "var(--mantine-color-red-5)",
                        }}
                      />
                      <Text size="xs" c="dimmed">Errors</Text>
                    </Group>
                  </Group>
                </Group>
                
                {hasChartData ? (
                  <LineChart
                    key={`chart-${timeRange}`}
                    h={180}
                    data={chartData}
                    dataKey="timestamp"
                    series={[
                      { name: "Triggers", color: "orange.5" },
                      { name: "Non-Matches", color: "green.5" },
                      { name: "Errors", color: "red.5" },
                    ]}
                    curveType="monotone"
                    withLegend={false}
                    withDots={chartData.length <= 15}
                    tooltipAnimationDuration={200}
                    gridAxis="xy"
                    xAxisProps={{
                      tickMargin: 8,
                      tick: { fontSize: 10, fill: "var(--mantine-color-text)" },
                    }}
                    yAxisProps={{
                      tickMargin: 8,
                      tick: { fontSize: 10, fill: "var(--mantine-color-text)" },
                      allowDecimals: false,
                      width: 30,
                    }}
                    lineProps={{
                      isAnimationActive: true,
                      animationDuration: 1000,
                      animationEasing: "ease-out",
                    }}
                  />
                ) : (
                  <Box 
                    flex={1} 
                    style={{ 
                      display: "flex", 
                      flexDirection: "column",
                      alignItems: "center", 
                      justifyContent: "center",
                      gap: 4,
                    }}
                  >
                    <Text size="sm" c="dimmed" fw={500}>
                      No data available
                    </Text>
                    <Text size="xs" c="dimmed">
                      Try adjusting the time range or wait for controls to be executed
                    </Text>
                  </Box>
                )}
              </Stack>
            </Box>
          </Grid.Col>

          {/* Right: Actions Distribution */}
          <Grid.Col span={4}>
            <Box
              p="md"
              style={{
                borderRadius: "var(--mantine-radius-sm)",
                backgroundColor: "var(--mantine-color-default)",
                border: "1px solid var(--mantine-color-default-border)",
                height: "100%",
                display: "flex",
                flexDirection: "column",
              }}
            >
              <Text size="sm" fw={600} mb="md">
                Actions Distribution
              </Text>

              {summary.totalMatches > 0 ? (
                <Stack 
                  flex={1} 
                  align="center" 
                  justify="center"
                  gap="lg"
                >
                  {/* Donut Chart - larger, animated on data change */}
                  <RingProgress
                    size={130}
                    thickness={14}
                    sections={[
                      {
                        value: summary.actionCounts?.allow !== undefined
                          ? (summary.actionCounts.allow / summary.totalMatches) * 100 * ringAnimationProgress
                          : 0,
                        color: "var(--mantine-color-green-4)",
                        tooltip: `Allow: ${summary.actionCounts?.allow || 0}`,
                      },
                      {
                        value: summary.actionCounts?.deny !== undefined
                          ? (summary.actionCounts.deny / summary.totalMatches) * 100 * ringAnimationProgress
                          : 0,
                        color: "var(--mantine-color-red-4)",
                        tooltip: `Deny: ${summary.actionCounts?.deny || 0}`,
                      },
                      {
                        value: summary.actionCounts?.warn !== undefined
                          ? (summary.actionCounts.warn / summary.totalMatches) * 100 * ringAnimationProgress
                          : 0,
                        color: "var(--mantine-color-yellow-4)",
                        tooltip: `Warn: ${summary.actionCounts?.warn || 0}`,
                      },
                      {
                        value: summary.actionCounts?.log !== undefined
                          ? (summary.actionCounts.log / summary.totalMatches) * 100 * ringAnimationProgress
                          : 0,
                        color: "var(--mantine-color-blue-4)",
                        tooltip: `Log: ${summary.actionCounts?.log || 0}`,
                      },
                    ]}
                    label={
                      <Stack gap={0} align="center">
                        <Text size="xl" fw={700}>
                          {summary.totalMatches}
                        </Text>
                        <Text size="xs" c="dimmed">triggers</Text>
                      </Stack>
                    }
                  />

                  {/* Legend - horizontal layout */}
                  <Group gap="md" justify="center" wrap="wrap">
                    {[
                      { key: "allow", label: "Allow", color: "green" },
                      { key: "deny", label: "Deny", color: "red" },
                      { key: "warn", label: "Warn", color: "yellow" },
                      { key: "log", label: "Log", color: "blue" },
                    ].map(({ key, label, color }) => {
                      const count = summary.actionCounts?.[key] ?? 0;
                      if (count === 0) return null;
                      const percentage = ((count / summary.totalMatches) * 100).toFixed(0);
                      return (
                        <Group key={key} gap={4}>
                          <Box
                            w={10}
                            h={10}
                            style={{
                              borderRadius: 2,
                              backgroundColor: `var(--mantine-color-${color}-4)`,
                            }}
                          />
                          <Text size="xs" fw={500}>{label}</Text>
                          <Text size="xs" fw={600} c={`${color}.6`}>
                            {count} ({percentage}%)
                          </Text>
                        </Group>
                      );
                    })}
                  </Group>
                </Stack>
              ) : (
                <Box 
                  flex={1} 
                  style={{ 
                    display: "flex", 
                    flexDirection: "column",
                    alignItems: "center", 
                    justifyContent: "center",
                    gap: 4,
                  }}
                >
                  <Text size="sm" c="dimmed" fw={500}>
                    No triggers yet
                  </Text>
                  <Text size="xs" c="dimmed" ta="center">
                    Actions will appear when controls match
                  </Text>
                </Box>
              )}
            </Box>
          </Grid.Col>
        </Grid>
      </Stack>
    </Card>
  );
}
