import { apiClient } from '@/lib/api/client';

export interface SchoolMoment {
  id: string;
  category: string;
  severity: 'alert' | 'warning' | 'info';
  title: string;
  message: string;
  requires_purchases: boolean;
}

export interface SchoolMomentsResponse {
  moments: SchoolMoment[];
}

export function getSchoolMoments() {
  return apiClient<SchoolMomentsResponse>('/school/moments');
}
