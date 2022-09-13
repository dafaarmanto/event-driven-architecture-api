import os
import json
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis_om import get_redis_connection, HashModel
from dotenv import load_dotenv
from consumers import CONSUMERS


load_dotenv()
app = FastAPI()


# Allow Frontend to connect
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:3000'],
  allow_methods=['*'],
  allow_headers=['*']
)


redis = get_redis_connection(
  host=os.getenv("HOST"),
  port=os.getenv("PORT"),
  password=os.getenv("PASSWORD"),
  decode_responses=True
)


class Delivery(HashModel):
  budget: int = 0
  notes: str = ''

  class Meta:
    database = redis


class Event(HashModel):
  delivery_id: str = None
  type: str
  data: str

  class Meta:
    database = redis


@app.get('/deliveries/{pk}/status')
async def get_state(pk: str):
  state = redis.get(f'delivery:{pk}')
  
  if state is not None:
    return json.loads(state)

  state = build_state(pk)
  redis.set(f'delivery:{pk}', json.dumps(state))
  return state


def build_state(pk: str):
  state = {}
  pks = Event.all_pks()
  all_events = [Event.get(pk) for pk in pks]
  events = [event for event in all_events if event.delivery_id == pk]

  for event in events:
    state = CONSUMERS[event.type](state, event)

  return state


@app.post('/deliveries/create')
async def create(request: Request):
  body = await request.json()
  delivery = Delivery(budget=body['data']['budget'], notes=body['data']['notes']).save()
  event = Event(delivery_id=delivery.pk, type=body['type'], data=json.dumps(body['data'])).save()
  state = CONSUMERS[event.type]({}, event)
  redis.set(f'delivery:{delivery.pk}', json.dumps(state))
  return state


@app.post('/event')
async def dispatch(request: Request):
  body = await request.json()
  delivery_id = body['delivery_id']
  event = Event(delivery_id=delivery_id, type=body['type'], data=json.dumps(body['data'])).save()
  state = await get_state(delivery_id)
  new_state = CONSUMERS[event.type](state, event)
  redis.set(f'delivery:{delivery_id}', json.dumps(new_state))
  return new_state