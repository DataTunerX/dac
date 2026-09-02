import { Type } from '@sinclair/typebox';

export const HealthOkSchema = Type.Object({
  status: Type.Literal('ok'),
  service: Type.Literal('tdb-gateway'),
  version: Type.Literal('v2')
});

export const ErrorSchema = Type.Object({
  error: Type.Object({
    code: Type.String(),
    message: Type.String(),
    details: Type.Optional(Type.Unknown())
  })
});
