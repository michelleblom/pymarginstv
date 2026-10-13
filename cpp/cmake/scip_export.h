/* Export macros for linking against the prebuilt SCIP shared library. */
#ifndef SCIP_EXPORT_H
#define SCIP_EXPORT_H

#define SCIP_EXPORT __attribute__((visibility("default")))
#define SCIP_NO_EXPORT __attribute__((visibility("hidden")))
#define SCIP_DEPRECATED __attribute__((__deprecated__))
#define SCIP_DEPRECATED_EXPORT SCIP_EXPORT SCIP_DEPRECATED
#define SCIP_DEPRECATED_NO_EXPORT SCIP_NO_EXPORT SCIP_DEPRECATED

#endif
