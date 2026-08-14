import {
  TASKS_NAV_LABEL,
  TASKS_NAV_ICON,
  SHOW_TASKS_NAV,
  PRODUCT_ARCHETYPE,
} from '@/product-config'
import { LayoutDashboard } from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'General',
      items: [
        {
          title: 'Dashboard',
          url: '/',
          icon: LayoutDashboard,
        },
        ...(SHOW_TASKS_NAV
          ? [
              {
                title: TASKS_NAV_LABEL,
                url:
                  PRODUCT_ARCHETYPE === 'monitor'
                    ? '/sources'
                    : '/tasks',
                icon: TASKS_NAV_ICON,
              },
            ]
          : []),
      ],
    },
  ],
}
