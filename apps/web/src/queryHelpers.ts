export interface QueryLike {
  isPending: boolean;
  isError: boolean;
  isFetching?: boolean;
  error: unknown;
  refetch: () => unknown;
}

export function hasQueryIssue(queries: QueryLike[]) {
  return queries.some((query) => query.isPending || query.isError);
}
