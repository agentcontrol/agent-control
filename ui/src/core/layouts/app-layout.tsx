import {
  AppShell,
  Box,
  Divider,
  Group,
  Stack,
  Text,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import {
  IconBook,
  IconChevronRight,
  IconHexagons,
  IconMoon,
  IconSun,
} from '@tabler/icons-react';
import { AnimatePresence, motion } from 'motion/react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { type ReactNode, useState } from 'react';

import { ErrorBoundary } from '@/components/error-boundary';
import { AcIcon } from '@/components/icons/ac-icon';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';

// import { useAgentsInfinite } from "@/core/hooks/query-hooks/use-agents-infinite";
import classes from './app-layout.module.css';

type AppLayoutProps = {
  children: ReactNode;
};

type NavItemProps = {
  href: string;
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
};

// TODO: Re-enable when agent list is added back
// interface AgentItemProps {
//   href: string;
//   label: string;
//   active?: boolean;
//   onClick?: () => void;
// }

function NavItem({ href, icon, label, active, onClick }: NavItemProps) {
  return (
    <UnstyledButton
      component={Link}
      href={href}
      className={classes.navItem}
      data-active={active || undefined}
      onClick={onClick}
      title={label}
    >
      <Group gap="sm" wrap="nowrap">
        <Box className={classes.navIcon}>{icon}</Box>
        <Text size="sm" className={classes.navLabel}>
          {label}
        </Text>
      </Group>
    </UnstyledButton>
  );
}

// TODO: Re-enable when agent list is added back
// function AgentItem({ href, label, active, onClick }: AgentItemProps) {
//   return (
//     <UnstyledButton
//       component={Link}
//       href={href}
//       className={classes.agentItem}
//       data-active={active || undefined}
//       onClick={onClick}
//     >
//       <Text size='sm'>{label}</Text>
//     </UnstyledButton>
//   );
// }

function BottomSection() {
  const { colorScheme: _colorScheme, toggleColorScheme } =
    useMantineColorScheme();

  return (
    <Stack gap={0} p="md">
      <Divider mb="md" className={classes.divider} />

      {/* Docs - GitHub README */}
      <UnstyledButton
        component="a"
        href="https://github.com/agentcontrol/agent-control/blob/main/README.md"
        target="_blank"
        rel="noopener noreferrer"
        className={classes.navItem}
        title="Docs"
      >
        <Group gap="sm" wrap="nowrap">
          <Box className={classes.navIcon}>
            <IconBook size={18} stroke={2} />
          </Box>
          <Text size="sm" className={classes.navLabel}>
            Docs
          </Text>
        </Group>
      </UnstyledButton>

      {/* Light/Dark Mode Toggle */}
      <UnstyledButton
        className={classes.navItem}
        onClick={() => toggleColorScheme()}
      >
        <Group gap="sm" wrap="nowrap">
          <Box className={classes.navIcon}>
            <Box className={classes.lightIcon}>
              <IconMoon size={18} stroke={2} />
            </Box>
            <Box className={classes.darkIcon}>
              <IconSun size={18} stroke={2} />
            </Box>
          </Box>
          <Text size="sm" className={classes.navLabel}>
            <span className={classes.lightIcon}>Dark mode</span>
            <span className={classes.darkIcon}>Light mode</span>
          </Text>
        </Group>
      </UnstyledButton>
    </Stack>
  );
}

// Simple logo icon (red asterisk/flower)

export function AppLayout({ children }: AppLayoutProps) {
  const router = useRouter();
  const [mobileOpened, setMobileOpened] = useState(false);
  const [desktopOpened, _setDesktopOpened] = useState(true);
  // TODO: Agent list temporarily disabled in sidebar
  // Reconsidering pagination strategy for navigation sidebar
  // const {
  //   data,
  //   isLoading: agentsLoading,
  // } = useAgentsInfinite();

  // const allAgents = data?.pages.flatMap((page) => page.agents) || [];

  const closeNavbar = () => {
    setMobileOpened(false);
  };

  return (
    <AppShell
      navbar={{
        width: desktopOpened ? 220 : 70,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened },
      }}
      padding={0}
    >
      <AppShell.Header className={classes.header}>
        <Header />
      </AppShell.Header>

      <AppShell.Navbar
        className={classes.navbar}
        data-collapsed={!desktopOpened || undefined}
      >
        <Stack gap={0} h="100%" justify="space-between">
          {/* Top Section */}
          <Stack gap={0}>
            <Stack px="md">
              <Group h="50px" justify="space-between" align="center">
                <UnstyledButton component={Link} href="/">
                  <Group gap="xs">
                    <Box className={classes.logoIcon} component="span">
                      <AcIcon size={32} />
                    </Box>
                    <Text size="md" fw={600}>
                      Agent Control
                    </Text>
                  </Group>
                </UnstyledButton>
                {/* <ActionIcon
                  onClick={() => setDesktopOpened(!desktopOpened)}
                  variant='subtle'
                  color='gray'
                  size='lg'
                  visibleFrom='sm'
                  disabled
                >
                  <ToggleMenu /> */}
                {/* </ActionIcon> */}
              </Group>
            </Stack>

            <Divider className={classes.divider} />

            <Stack gap={4} p="md">
              <NavItem
                href="/"
                icon={
                  <IconHexagons
                    color="var(--jds-color-muted-foreground)"
                    size={18}
                    stroke={2}
                  />
                }
                label="My agents"
                active={
                  router.pathname === '/' ||
                  router.pathname.startsWith('/agents')
                }
                onClick={closeNavbar}
              />

              {/* Agent List - Temporarily hidden */}
              {/* TODO: Decide on pagination strategy for sidebar agent list */}
              {/* {desktopOpened && (
                <Box
                  className={classes.agentListContainer}
                  style={{
                    maxHeight: "300px",
                    overflow: "auto",
                  }}
                >
                  <Stack gap={2} ml='lg' mt={4} className={classes.agentList}>
                    {agentsLoading ? (
                      <Center py='xs'>
                        <Loader size='xs' />
                      </Center>
                    ) : (
                      <>
                        {allAgents.map((agent) => (
                          <AgentItem
                            key={agent.agent_id}
                            href={`/agents/${agent.agent_id}/controls`}
                            label={agent.agent_name}
                            active={router.query.id === agent.agent_id}
                            onClick={closeNavbar}
                          />
                        ))}
                      </>
                    )}
                  </Stack>
                </Box>
              )} */}

              {/* TODO: Re-enable when controls page is implemented */}
              {/* <NavItem
                href='/controls'
                icon={<IconAutomaticGearbox size={18} stroke={2} />}
                label='All controls'
                onClick={closeNavbar}
              /> */}
            </Stack>
          </Stack>

          {/* Bottom Section */}
          <BottomSection />
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main className={classes.main}>
        <ErrorBoundary variant="content">{children}</ErrorBoundary>
      </AppShell.Main>
    </AppShell>
  );
}

const BREADCRUMB_TRANSITION = { duration: 0.2, ease: 'easeOut' as const };

function Header() {
  const router = useRouter();
  const isAgentPage =
    router.pathname.startsWith('/agents') && !!router.query.id;
  const agentId = isAgentPage ? (router.query.id as string) : '';
  const { data: agentData } = useAgent(agentId);
  const agentDisplayName = agentData?.agent?.agent_name ?? agentId ?? null;

  const getBreadcrumb = () => {
    if (router.pathname !== '/' && !router.pathname.startsWith('/agents')) {
      return null;
    }

    if (!isAgentPage) {
      return (
        <Text size="sm" fw={500}>
          My agents
        </Text>
      );
    }

    return (
      <Group gap="xs" align="center" wrap="nowrap">
        <Text
          component={Link}
          href="/"
          size="sm"
          fw={500}
          c="dimmed"
          style={{ textDecoration: 'none' }}
          data-testid="breadcrumb-my-agents"
        >
          My agents
        </Text>
        <AnimatePresence mode="wait">
          {!!agentDisplayName && (
            <motion.span
              key="agent-breadcrumb"
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -6 }}
              transition={BREADCRUMB_TRANSITION}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 'var(--mantine-spacing-xs)',
              }}
            >
              <IconChevronRight
                size={14}
                color="var(--mantine-color-dimmed)"
                style={{ flexShrink: 0 }}
              />
              <Text size="sm" fw={500} component="span">
                {agentDisplayName}
              </Text>
            </motion.span>
          )}
        </AnimatePresence>
      </Group>
    );
  };

  return (
    <Group h="100%" px="md" ml={200}>
      {getBreadcrumb()}
    </Group>
  );
}
