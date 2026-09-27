import {
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragCancelEvent,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { useRef } from 'react';

import type { Translate } from './types';
import { orderProjectsByIds, type WorkspaceProject } from './components/workspaceSettingsModel';

const POINTER_ACTIVATION_DISTANCE_PX = 6;

interface WorkspaceProjectDragControllerInput {
  disabled: boolean;
  generation: number;
  projects: WorkspaceProject[];
  t: Translate;
  onPreview: (projects: WorkspaceProject[]) => void;
  onPersist: (projectIds: string[]) => Promise<void>;
  onFailure: () => void;
}

export function moveProject(
  projects: WorkspaceProject[],
  activeId: string,
  overId: string
): WorkspaceProject[] {
  const projectIds = projects.map((project) => project.project_id);
  const activeIndex = projectIds.indexOf(activeId);
  const overIndex = projectIds.indexOf(overId);
  if (activeIndex < 0 || overIndex < 0 || activeIndex === overIndex) return projects;
  const nextIds = arrayMove(projectIds, activeIndex, overIndex);
  return orderProjectsByIds(projects, nextIds);
}

export function useWorkspaceProjectDragController({
  disabled,
  generation,
  projects,
  t,
  onPreview,
  onPersist,
  onFailure,
}: WorkspaceProjectDragControllerInput) {
  const snapshotRef = useRef<{ generation: number; projects: WorkspaceProject[] } | null>(null);
  const generationRef = useRef(generation);
  generationRef.current = generation;
  const previewRef = useRef<WorkspaceProject[] | null>(null);
  const movedRef = useRef(false);
  const lastOverIdRef = useRef<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: POINTER_ACTIVATION_DISTANCE_PX },
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const previewMove = (activeId: string, overId: string): WorkspaceProject[] => {
    const base = snapshotRef.current?.projects ?? projects;
    const previous = previewRef.current ?? base;
    const next = moveProject(base, activeId, overId);
    previewRef.current = next;
    movedRef.current = next !== base;
    if (next !== previous) {
      onPreview(next);
    }
    return next;
  };

  const onDragStart = ({ active }: DragStartEvent) => {
    if (disabled || !projects.some((project) => project.project_id === String(active.id))) return;
    reset();
    snapshotRef.current = { generation, projects };
    previewRef.current = projects;
  };

  const onDragOver = ({ active, over }: DragOverEvent) => {
    if (disabled || !snapshotRef.current || !over) return;
    if (snapshotRef.current.generation !== generationRef.current) return reset();
    const overId = String(over.id);
    if (lastOverIdRef.current === overId) return;
    lastOverIdRef.current = overId;
    previewMove(String(active.id), overId);
  };

  const onDragEnd = async ({ active, over }: DragEndEvent) => {
    const dragSnapshot = snapshotRef.current;
    if (disabled || !dragSnapshot) return reset();
    if (dragSnapshot.generation !== generationRef.current) return reset();
    const snapshot = dragSnapshot.projects;
    if (!over) {
      onPreview(snapshot);
      return reset();
    }
    const next = movedRef.current
      ? (previewRef.current ?? snapshot)
      : previewMove(String(active.id), String(over.id));
    try {
      await onPersist(next.map((project) => project.project_id));
    } catch {
      if (dragSnapshot.generation === generationRef.current) {
        onPreview(snapshot);
        onFailure();
      }
    } finally {
      if (snapshotRef.current === dragSnapshot) reset();
    }
  };

  const onDragCancel = (_event: DragCancelEvent) => {
    const snapshot = snapshotRef.current;
    if (snapshot && snapshot.generation === generationRef.current) onPreview(snapshot.projects);
    reset();
  };

  const projectName = (id: string | number) =>
    projects.find((project) => project.project_id === String(id))?.display_name ?? String(id);
  const position = (id: string | number) =>
    projects.findIndex((project) => project.project_id === String(id)) + 1;

  const reset = () => {
    snapshotRef.current = null;
    previewRef.current = null;
    movedRef.current = false;
    lastOverIdRef.current = null;
  };

  return {
    sensors,
    onDragStart,
    onDragOver,
    onDragEnd,
    onDragCancel,
    accessibility: {
      screenReaderInstructions: {
        draggable: t('settings.workspace.drag.instructions'),
      },
      announcements: {
        onDragStart: ({ active }: DragStartEvent) =>
          t('settings.workspace.drag.start', { name: projectName(active.id) }),
        onDragOver: ({ active, over }: DragOverEvent) =>
          over
            ? t('settings.workspace.drag.over', {
                name: projectName(active.id),
                position: position(over.id),
              })
            : undefined,
        onDragEnd: ({ active, over }: DragEndEvent) =>
          over
            ? t('settings.workspace.drag.end', {
                name: projectName(active.id),
                position: position(over.id),
              })
            : t('settings.workspace.drag.cancel', { name: projectName(active.id) }),
        onDragCancel: ({ active }: DragCancelEvent) =>
          t('settings.workspace.drag.cancel', { name: projectName(active.id) }),
      },
    },
  };
}

export type WorkspaceProjectDragController = ReturnType<typeof useWorkspaceProjectDragController>;
