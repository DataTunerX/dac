import { Type } from '@sinclair/typebox';

import { ErrorSchema, HealthOkSchema } from './common.js';

export const HealthRouteSchema = {
  tags: ['health'],
  response: {
    200: HealthOkSchema,
    500: ErrorSchema
  }
} as const;

export const DbHealthRouteSchema = {
  tags: ['health'],
  response: {
    200: Type.Object({
      status: Type.Literal('ok'),
      database: Type.Literal('up')
    }),
    500: ErrorSchema
  }
} as const;
