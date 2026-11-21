import { timingSafeEqual } from 'node:crypto';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import fastifyJwt from '@fastify/jwt';
import type { Config } from '../config.js';

function safeEq(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export async function registerAuth(app: FastifyInstance, cfg: Config) {
  await app.register(fastifyJwt, {
    secret: cfg.jwt.secret,
    sign: { algorithm: 'HS256', expiresIn: cfg.jwt.expiresIn, iss: cfg.jwt.issuer, aud: cfg.jwt.audience },
    verify: { algorithms: ['HS256'], allowedIss: cfg.jwt.issuer, allowedAud: cfg.jwt.audience },
  });

  app.decorate('authenticate', async (req: FastifyRequest, reply: FastifyReply) => {
    try {
      await req.jwtVerify();
    } catch {
      return reply.code(401).send({ code: 'UNAUTHORIZED', message: 'Brak lub nieważny token JWT.' });
    }
  });

  app.post(
    '/api/v1/auth/token',
    {
      schema: {
        tags: ['auth'],
        body: {
          type: 'object',
          required: ['clientId', 'clientSecret'],
          properties: { clientId: { type: 'string', maxLength: 200 }, clientSecret: { type: 'string', maxLength: 200 } },
        },
      },
    },
    async (req, reply) => {
      const { clientId, clientSecret } = req.body as { clientId: string; clientSecret: string };
      if (!safeEq(clientId, cfg.auth.clientId) || !safeEq(clientSecret, cfg.auth.clientSecret)) {
        return reply.code(401).send({ code: 'UNAUTHORIZED', message: 'Niepoprawne dane klienta.' });
      }
      const accessToken = app.jwt.sign({ sub: clientId });
      const { exp, iat } = app.jwt.decode<{ exp: number; iat: number }>(accessToken)!;
      return { accessToken, tokenType: 'Bearer', expiresIn: exp - iat };
    },
  );
}

declare module 'fastify' {
  interface FastifyInstance {
    authenticate: (req: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }
}
