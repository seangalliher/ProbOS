export interface WorkItemStepLike {
  status: string;
}

export function isWorkItemStepComplete(step: WorkItemStepLike): boolean {
  return step.status === 'done' || step.status === 'completed';
}

export function countCompletedWorkItemSteps(steps: readonly WorkItemStepLike[]): number {
  return steps.filter(isWorkItemStepComplete).length;
}
