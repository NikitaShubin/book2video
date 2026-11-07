IMAGE ?= book2video:latest
BOOK ?= /data/book.epub
OUT ?= /out/pilot.mp4
ALL_OUT ?= /out/book.mp4
CHAPTER ?= 4
SPEED ?= 1.2
PROVIDER ?= auto
ENCODER ?= auto
NO_GPU ?= 0

GPU_COMPOSE = docker compose -f compose.yaml -f compose.gpu.yaml
ifeq ($(GPU),1)
COMPOSE = $(GPU_COMPOSE)
else
COMPOSE ?= docker compose
endif

RUNTIME_FLAGS = --provider $(PROVIDER) $(if $(filter 1,$(NO_GPU)),--no-gpu)

.PHONY: image image-gpu build voices doctor inspect pilot all test check shell clean

image:
	$(COMPOSE) build

image-gpu:
	$(GPU_COMPOSE) build

# Alias kept for muscle memory: `make build` builds the image, not a video.
build: image

voices:
	$(COMPOSE) run --rm book2video voices

doctor:
	$(COMPOSE) run --rm book2video $(RUNTIME_FLAGS) doctor

inspect:
	$(COMPOSE) run --rm book2video inspect "$(BOOK)"

pilot:
	$(COMPOSE) run --rm book2video $(RUNTIME_FLAGS) build "$(BOOK)" \
		--chapter $(CHAPTER) --voice ru_m5 --sidebar-voice ru_f2 \
		--speed $(SPEED) --encoder $(ENCODER) --out "$(OUT)"

all:
	$(COMPOSE) run --rm book2video $(RUNTIME_FLAGS) build "$(BOOK)" \
		--all --voice ru_m5 --sidebar-voice ru_f2 \
		--speed $(SPEED) --encoder $(ENCODER) --out "$(ALL_OUT)"

test:
	$(COMPOSE) run --rm --entrypoint sh book2video -c \
		'cd /data/book2video && python -m unittest discover -s tests -t tests -v'

check: test
	$(COMPOSE) run --rm book2video $(RUNTIME_FLAGS) --help >/dev/null

shell:
	$(COMPOSE) run --rm --entrypoint bash book2video

clean:
	find out -mindepth 1 ! -name .gitkeep -delete
