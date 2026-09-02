import { Type } from '@sinclair/typebox';

export const UuidSchema = Type.String({ format: 'uuid' });
export const TimestampSchema = Type.String({ format: 'date-time' });

export const JsonValueSchema = Type.Any();

export const AsOfQuerySchema = Type.Object({
  as_of_valid_time: TimestampSchema,
  as_of_system_time: Type.Optional(TimestampSchema)
});
